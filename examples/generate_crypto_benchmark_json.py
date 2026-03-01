#!/usr/bin/env python3
"""
Generate BTC and universe equal-weight benchmark data for the dashboard.

Output:
  examples/dashboard/public/crypto_benchmark_data.json
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Tuple


SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "stock_tracking_db.sqlite"
DEFAULT_OUTPUT_PATH = SCRIPT_DIR / "dashboard" / "public" / "crypto_benchmark_data.json"

DEFAULT_UNIVERSE_SYMBOLS = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "BNB-USD",
    "XRP-USD",
    "ADA-USD",
    "DOGE-USD",
    "AVAX-USD",
    "LINK-USD",
    "DOT-USD",
    "TRX-USD",
    "XLM-USD",
    "LTC-USD",
    "BCH-USD",
    "ATOM-USD",
    "NEAR-USD",
]

COINGECKO_ID_BY_SYMBOL = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "DOGE-USD": "dogecoin",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "DOT-USD": "polkadot",
    "TRX-USD": "tron",
    "XLM-USD": "stellar",
    "LTC-USD": "litecoin",
    "BCH-USD": "bitcoin-cash",
    "ATOM-USD": "cosmos",
    "NEAR-USD": "near",
}


def _safe_float(v, default=0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _classify_exit_reason_from_metadata(metadata: str | None) -> str:
    text = (metadata or "").strip().lower()
    if not text:
        return "normal"
    if "exit_category" in text:
        if "rotation" in text:
            return "rotation"
        if "stop_loss" in text or "stop-loss" in text:
            return "stop_loss"
        if "normal" in text:
            return "normal"
    if "rotation replace:" in text:
        return "rotation"
    if "stop loss" in text or "trailing stop" in text or "loss guard" in text:
        return "stop_loss"
    return "normal"


def load_trade_summary(conn: sqlite3.Connection) -> Tuple[Dict[str, float], int, float]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            DATE(sell_date) AS d,
            SUM(
                CASE
                    WHEN notional_usd IS NOT NULL THEN notional_usd * (profit_rate / 100.0)
                    WHEN quantity IS NOT NULL THEN quantity * buy_price * (profit_rate / 100.0)
                    ELSE 0
                END
            ) AS pnl
        FROM crypto_trading_history
        WHERE sell_date IS NOT NULL
        GROUP BY DATE(sell_date)
        ORDER BY d
        """
    )
    pnl_by_day = {row[0]: _safe_float(row[1]) for row in cursor.fetchall() if row[0]}

    cursor.execute("SELECT COUNT(*), AVG(CASE WHEN profit_rate > 0 THEN 1.0 ELSE 0.0 END) FROM crypto_trading_history")
    trade_count, win_rate = cursor.fetchone()

    return pnl_by_day, int(trade_count or 0), _safe_float(win_rate) * 100.0


def load_unrealized_pnl(conn: sqlite3.Connection) -> Tuple[float, int]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            SUM(
                CASE
                    WHEN current_price IS NOT NULL AND quantity IS NOT NULL
                    THEN (current_price - buy_price) * quantity
                    ELSE 0
                END
            ) AS unrealized,
            COUNT(*)
        FROM crypto_holdings
        """
    )
    row = cursor.fetchone()
    return _safe_float(row[0]), int(row[1] or 0)


def load_current_holdings(conn: sqlite3.Connection) -> List[Dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            symbol,
            buy_date,
            quantity,
            buy_price,
            current_price,
            notional_usd
        FROM crypto_holdings
        ORDER BY buy_date ASC
        """
    )
    rows = cursor.fetchall()
    raw_holdings: List[Dict] = []
    for row in rows:
        symbol, buy_date, quantity, buy_price, current_price, notional_usd = row
        qty = _safe_float(quantity)
        bp = _safe_float(buy_price)
        cp = _safe_float(current_price)
        market_value = cp * qty
        unrealized_pnl = (cp - bp) * qty
        cost_basis = bp * qty if bp > 0 and qty > 0 else _safe_float(notional_usd)
        profit_rate = (unrealized_pnl / cost_basis * 100.0) if cost_basis > 0 else 0.0

        raw_holdings.append(
            {
                "symbol": str(symbol),
                "buy_date": str(buy_date),
                "quantity": round(qty, 8),
                "buy_price": round(bp, 8),
                "current_price": round(cp, 8),
                "notional_usd": round(_safe_float(notional_usd), 6),
                "market_value_usd": round(market_value, 6),
                "unrealized_pnl_usd": round(unrealized_pnl, 6),
                "profit_rate_pct": round(profit_rate, 4),
            }
        )
    total_market_value = sum(_safe_float(h.get("market_value_usd")) for h in raw_holdings)
    holdings: List[Dict] = []
    for h in raw_holdings:
        mv = _safe_float(h.get("market_value_usd"))
        weight = (mv / total_market_value * 100.0) if total_market_value > 0 else 0.0
        h["weight_pct"] = round(weight, 4)
        holdings.append(h)
    return holdings


def load_order_executions(conn: sqlite3.Connection, limit: int = 200) -> List[Dict]:
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT
            created_at,
            symbol,
            side,
            status,
            executed_price,
            quantity,
            quote_amount,
            fee_amount,
            order_type,
            mode,
            metadata
        FROM crypto_order_executions
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cursor.fetchall()

    history_rows = conn.execute(
        """
        SELECT symbol, sell_date, profit_rate
        FROM crypto_trading_history
        WHERE sell_date IS NOT NULL
        """
    ).fetchall()

    history_by_symbol: Dict[str, List[Tuple[datetime, float]]] = {}
    for h_symbol, h_sell_date, h_profit_rate in history_rows:
        try:
            dt = datetime.strptime(str(h_sell_date), "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        history_by_symbol.setdefault(str(h_symbol), []).append((dt, _safe_float(h_profit_rate)))

    for symbol_key in history_by_symbol:
        history_by_symbol[symbol_key].sort(key=lambda x: x[0])

    def _find_sell_profit_rate(symbol: str, created_at: str) -> float | None:
        items = history_by_symbol.get(symbol, [])
        if not items:
            return None
        try:
            created_dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

        best_diff = None
        best_rate = None
        for sell_dt, profit_rate in items:
            diff = abs((sell_dt - created_dt).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_rate = profit_rate

        # Match only when timestamp is reasonably close (same cycle / same trade)
        if best_diff is not None and best_diff <= 300:
            return best_rate
        return None

    items: List[Dict] = []
    for row in rows:
        created_at, symbol, side, status, executed_price, quantity, quote_amount, fee_amount, order_type, mode, metadata = row
        side_str = str(side)
        exit_type = None
        exit_reason_type = None
        realized_pnl_pct = None
        if side_str.lower() == "sell":
            realized_pnl_pct = _find_sell_profit_rate(str(symbol), str(created_at))
            exit_reason_type = _classify_exit_reason_from_metadata(str(metadata) if metadata is not None else None)
            if realized_pnl_pct is not None:
                if realized_pnl_pct > 0:
                    exit_type = "take_profit"
                elif realized_pnl_pct < 0:
                    exit_type = "stop_loss"
                else:
                    exit_type = "breakeven"

        items.append(
            {
                "created_at": str(created_at),
                "symbol": str(symbol),
                "side": side_str,
                "status": str(status),
                "executed_price": round(_safe_float(executed_price), 8),
                "quantity": round(_safe_float(quantity), 8),
                "quote_amount": round(_safe_float(quote_amount), 6),
                "fee_amount": round(_safe_float(fee_amount), 6),
                "order_type": str(order_type),
                "mode": str(mode),
                "realized_pnl_pct": None if realized_pnl_pct is None else round(_safe_float(realized_pnl_pct), 4),
                "exit_type": exit_type,
                "exit_reason_type": exit_reason_type,
            }
        )
    return items


def load_exit_reason_counts(conn: sqlite3.Connection, start_date: str | None = None) -> Dict[str, int]:
    cursor = conn.cursor()
    if start_date:
        cursor.execute(
            """
            SELECT metadata
            FROM crypto_order_executions
            WHERE side = 'sell' AND status = 'filled' AND DATE(created_at) >= DATE(?)
            """,
            (start_date,),
        )
    else:
        cursor.execute(
            """
            SELECT metadata
            FROM crypto_order_executions
            WHERE side = 'sell' AND status = 'filled'
            """
        )
    counts = {"stop_loss": 0, "rotation": 0, "normal": 0}
    for (metadata,) in cursor.fetchall():
        k = _classify_exit_reason_from_metadata(str(metadata) if metadata is not None else None)
        if k not in counts:
            k = "normal"
        counts[k] += 1
    return counts


def load_recent_cycles(log_dir: Path, limit: int = 20, stale_minutes: int = 30) -> List[Dict]:
    if not log_dir.exists():
        return []

    files = sorted(log_dir.glob("crypto_scheduler_*.log"))
    if not files:
        return []

    line_re = re.compile(r"^\[(?P<ts>[\d\-:\s]+)\]\s(?P<msg>.*)$")
    phase_re = re.compile(r"entry=(\d+),\s*no_entry=(\d+),\s*sold=(\d+)")

    cycles: List[Dict] = []
    current: Dict | None = None

    for file in files[-3:]:
        try:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for line in lines:
            m = line_re.match(line)
            if not m:
                continue
            ts = m.group("ts").strip()
            msg = m.group("msg").strip()

            if msg == "Crypto hourly paper cycle started":
                if current:
                    current["status"] = "running"
                    cycles.append(current)
                current = {
                    "started_at": ts,
                    "ended_at": None,
                    "status": "running",
                    "entry_count": 0,
                    "no_entry_count": 0,
                    "sold_count": 0,
                    "error": None,
                    "_phase3_done": False,
                }
                continue

            if not current:
                continue

            if "Crypto phase3 process complete" in msg:
                pm = phase_re.search(msg)
                if pm:
                    current["entry_count"] = int(pm.group(1))
                    current["no_entry_count"] = int(pm.group(2))
                    current["sold_count"] = int(pm.group(3))
                current["_phase3_done"] = True
                continue

            if msg == "Crypto hourly paper cycle completed":
                current["ended_at"] = ts
                current["status"] = "success"
                cycles.append(current)
                current = None
                continue

            # generate step emits this before the final "cycle completed" marker.
            # Treat it as terminal success so freshly generated JSON does not keep
            # the same cycle in RUNNING state until the next cycle.
            if msg.startswith("Saved:") and "crypto_benchmark_data.json" in msg:
                current["ended_at"] = ts
                current["status"] = "success"
                cycles.append(current)
                current = None
                continue

            if "failed with exit code" in msg:
                current["ended_at"] = ts
                current["status"] = "failed"
                current["error"] = msg
                cycles.append(current)
                current = None
                continue

    if current:
        cycles.append(current)

    # Normalize stale/incomplete cycles:
    # - If a later terminal cycle exists, earlier RUNNING entries are ABORTED.
    # - If the latest RUNNING is too old, mark FAILED(stale).
    seen_later_terminal = False
    now_dt = datetime.now()
    now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")
    for i in range(len(cycles) - 1, -1, -1):
        c = cycles[i]
        status = str(c.get("status", ""))
        if status in ("success", "failed"):
            seen_later_terminal = True
            continue
        if status != "running":
            continue

        if seen_later_terminal:
            c["status"] = "aborted"
            c["ended_at"] = c.get("ended_at") or c.get("started_at")
            c["error"] = c.get("error") or "Superseded by a later cycle"
            continue

        try:
            started = datetime.strptime(str(c.get("started_at")), "%Y-%m-%d %H:%M:%S")
            age_min = (now_dt - started).total_seconds() / 60.0
            # During benchmark generation, this cycle's trailing
            # "Saved/completed" log lines might not be written yet.
            # If phase3 is already complete, treat as successful end.
            if c.get("_phase3_done"):
                c["status"] = "success"
                c["ended_at"] = c.get("ended_at") or now_str
                c["error"] = None
                continue
            if age_min >= stale_minutes:
                c["status"] = "failed"
                c["ended_at"] = c.get("ended_at") or now_str
                c["error"] = c.get("error") or f"No completion log after {int(age_min)} minutes (stale)"
        except Exception:
            pass

    for c in cycles:
        c.pop("_phase3_done", None)

    cycles = list(reversed(cycles))
    return cycles[:limit]


def get_strategy_start_date(conn: sqlite3.Connection) -> str:
    """Return first strategy entry date (YYYY-MM-DD)."""
    cursor = conn.cursor()

    queries = [
        "SELECT MIN(DATE(created_at)) FROM crypto_order_executions WHERE side = 'buy' AND status = 'filled'",
        "SELECT MIN(DATE(buy_date)) FROM crypto_holdings",
        "SELECT MIN(DATE(buy_date)) FROM crypto_trading_history",
    ]
    for q in queries:
        cursor.execute(q)
        row = cursor.fetchone()
        if row and row[0]:
            return str(row[0])

    return datetime.now().date().isoformat()


def fetch_btc_daily(days: int) -> List[Tuple[str, float]]:
    query = urllib.parse.urlencode({
        "vs_currency": "usd",
        "days": str(days),
        "interval": "daily",
    })
    url = f"https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "prism-insight/crypto-benchmark"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    prices = payload.get("prices", [])
    rows: List[Tuple[str, float]] = []
    for item in prices:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts_ms = int(item[0])
        price = _safe_float(item[1])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()
        rows.append((dt, price))
    dedup = {}
    for d, p in rows:
        dedup[d] = p
    return sorted(dedup.items(), key=lambda x: x[0])


def fetch_symbol_daily_from_coingecko(coin_id: str, days: int) -> List[Tuple[str, float]]:
    query = urllib.parse.urlencode({
        "vs_currency": "usd",
        "days": str(days),
        "interval": "daily",
    })
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "prism-insight/crypto-benchmark"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    prices = payload.get("prices", [])
    rows: List[Tuple[str, float]] = []
    for item in prices:
        if not isinstance(item, list) or len(item) < 2:
            continue
        ts_ms = int(item[0])
        price = _safe_float(item[1])
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).date().isoformat()
        rows.append((dt, price))
    dedup = {}
    for d, p in rows:
        dedup[d] = p
    return sorted(dedup.items(), key=lambda x: x[0])


def build_universe_equal_weight_series(
    period_days: int,
    date_axis: List[str],
    symbols: List[str] | None = None,
) -> List[Tuple[str, float]]:
    if not date_axis:
        return []
    universe = symbols or DEFAULT_UNIVERSE_SYMBOLS

    symbol_daily: Dict[str, Dict[str, float]] = {}
    for symbol in universe:
        coin_id = COINGECKO_ID_BY_SYMBOL.get(symbol)
        if not coin_id:
            continue
        try:
            rows = fetch_symbol_daily_from_coingecko(coin_id, period_days)
            if not rows:
                continue
            symbol_daily[symbol] = {d: _safe_float(p) for d, p in rows if _safe_float(p) > 0}
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            continue

    if not symbol_daily:
        return []

    axis_sorted = sorted(date_axis)
    first_date = axis_sorted[0]

    baselines: Dict[str, float] = {}
    for symbol, by_date in symbol_daily.items():
        baseline = by_date.get(first_date)
        if not baseline or baseline <= 0:
            continue
        baselines[symbol] = baseline

    if not baselines:
        return []

    last_price: Dict[str, float] = {}
    out: List[Tuple[str, float]] = []
    for d in axis_sorted:
        returns: List[float] = []
        for symbol, baseline in baselines.items():
            cur = symbol_daily.get(symbol, {}).get(d)
            if cur and cur > 0:
                last_price[symbol] = cur
            cur_price = last_price.get(symbol)
            if not cur_price or baseline <= 0:
                continue
            returns.append((cur_price / baseline - 1.0) * 100.0)
        if returns:
            out.append((d, sum(returns) / len(returns)))
        elif out:
            out.append((d, out[-1][1]))
        else:
            out.append((d, 0.0))
    return out


def fetch_btc_daily_since(start_date: str) -> List[Tuple[str, float]]:
    start = datetime.fromisoformat(start_date).date()
    today = datetime.now().date()
    days = max(1, (today - start).days + 1)
    return fetch_btc_daily(days)


def fallback_btc_daily(conn: sqlite3.Connection, days: int) -> List[Tuple[str, float]]:
    cursor = conn.cursor()
    start_date = (datetime.now().date() - timedelta(days=days)).isoformat()

    cursor.execute(
        """
        SELECT DATE(created_at) AS d, AVG(executed_price)
        FROM crypto_order_executions
        WHERE symbol = 'BTC-USD' AND status = 'filled' AND created_at >= ?
        GROUP BY DATE(created_at)
        ORDER BY d
        """,
        (start_date,),
    )
    rows = [(r[0], _safe_float(r[1])) for r in cursor.fetchall() if r[0]]
    if rows:
        return rows

    cursor.execute("SELECT DATE(buy_date), buy_price FROM crypto_holdings WHERE symbol = 'BTC-USD' LIMIT 1")
    row = cursor.fetchone()
    if row and row[0]:
        return [(row[0], _safe_float(row[1]))]
    today = datetime.now().date().isoformat()
    return [(today, 0.0)]


def build_output(
    btc_daily: List[Tuple[str, float]],
    universe_ew_daily: List[Tuple[str, float]],
    pnl_by_day: Dict[str, float],
    initial_capital: float,
    period_days: int,
    trade_count: int,
    win_rate: float,
    unrealized_pnl: float,
    open_positions: int,
    holdings: List[Dict],
    order_executions: List[Dict],
    recent_cycles: List[Dict],
    exit_reason_counts: Dict[str, int],
    logic_change_ts: str,
) -> Dict:
    if not btc_daily:
        today = datetime.now().date().isoformat()
        btc_daily = [(today, 0.0)]

    baseline = _safe_float(btc_daily[0][1], 0.0)
    universe_by_date = {d: _safe_float(v) for d, v in universe_ew_daily}
    realized_pnl = 0.0
    points: List[Dict] = []

    for idx, (date_str, btc_price) in enumerate(btc_daily):
        realized_pnl += _safe_float(pnl_by_day.get(date_str))
        algo_equity = initial_capital + realized_pnl
        if idx == len(btc_daily) - 1:
            algo_equity += unrealized_pnl

        algo_return = ((algo_equity - initial_capital) / initial_capital) * 100.0 if initial_capital > 0 else 0.0
        btc_return = ((btc_price - baseline) / baseline) * 100.0 if baseline > 0 else 0.0
        benchmark_equity = initial_capital * (1.0 + (btc_return / 100.0))
        universe_return = _safe_float(universe_by_date.get(date_str), 0.0)
        universe_benchmark_equity = initial_capital * (1.0 + (universe_return / 100.0))

        points.append({
            "date": date_str,
            "btc_price": round(btc_price, 6),
            "btc_return_pct": round(btc_return, 4),
            "universe_return_pct": round(universe_return, 4),
            "algorithm_equity": round(algo_equity, 6),
            "algorithm_return_pct": round(algo_return, 4),
            "benchmark_equity": round(benchmark_equity, 6),
            "universe_benchmark_equity": round(universe_benchmark_equity, 6),
        })

    algo_final = points[-1]["algorithm_return_pct"]
    btc_final = points[-1]["btc_return_pct"]
    universe_final = points[-1]["universe_return_pct"]
    alpha = algo_final - btc_final
    universe_alpha = algo_final - universe_final

    stamped_orders = [
        {**order, "logic_change_ts": logic_change_ts} for order in order_executions
    ]
    stamped_cycles = [
        {**cycle, "logic_change_ts": logic_change_ts} for cycle in recent_cycles
    ]

    return {
        "generated_at": datetime.now().isoformat(),
        "period_days": period_days,
        "initial_capital": initial_capital,
        "logic_change_ts": logic_change_ts,
        "summary": {
            "algorithm_return_pct": round(algo_final, 4),
            "btc_return_pct": round(btc_final, 4),
            "alpha_pct": round(alpha, 4),
            "universe_return_pct": round(universe_final, 4),
            "universe_alpha_pct": round(universe_alpha, 4),
            "total_trades": trade_count,
            "win_rate": round(win_rate, 2),
            "open_positions": open_positions,
            "exit_reason_counts": {
                "stop_loss": int(exit_reason_counts.get("stop_loss", 0)),
                "rotation": int(exit_reason_counts.get("rotation", 0)),
                "normal": int(exit_reason_counts.get("normal", 0)),
            },
        },
        "points": points,
        "holdings": holdings,
        "order_executions": stamped_orders,
        "recent_cycles": stamped_cycles,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate crypto benchmark JSON for dashboard.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-path", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--days", type=int, default=None, help="Rolling window days. If omitted, uses strategy first-entry date.")
    parser.add_argument("--initial-capital", type=float, default=1000.0)
    args = parser.parse_args()

    db_path = Path(args.db_path)
    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        pnl_by_day, trade_count, win_rate = load_trade_summary(conn)
        unrealized_pnl, open_positions = load_unrealized_pnl(conn)
        holdings = load_current_holdings(conn)
        order_executions = load_order_executions(conn)
        recent_cycles = load_recent_cycles(PROJECT_ROOT / "logs")
        start_date = get_strategy_start_date(conn)
        exit_reason_counts = load_exit_reason_counts(conn, start_date=start_date)

        try:
            if args.days is not None and args.days > 0:
                period_days = int(args.days)
                btc_daily = fetch_btc_daily(period_days)
            else:
                btc_daily = fetch_btc_daily_since(start_date)
                if btc_daily:
                    period_days = max(1, (datetime.now().date() - datetime.fromisoformat(btc_daily[0][0]).date()).days + 1)
                else:
                    period_days = 1
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            if args.days is not None and args.days > 0:
                period_days = int(args.days)
            else:
                period_days = max(1, (datetime.now().date() - datetime.fromisoformat(start_date).date()).days + 1)
            btc_daily = fallback_btc_daily(conn, period_days)
        date_axis = [d for d, _ in btc_daily]
        universe_ew_daily = build_universe_equal_weight_series(period_days=period_days, date_axis=date_axis)

        logic_change_ts = datetime.now().isoformat()
        data = build_output(
            btc_daily=btc_daily,
            universe_ew_daily=universe_ew_daily,
            pnl_by_day=pnl_by_day,
            initial_capital=args.initial_capital,
            period_days=period_days,
            trade_count=trade_count,
            win_rate=win_rate,
            unrealized_pnl=unrealized_pnl,
            open_positions=open_positions,
            holdings=holdings,
            order_executions=order_executions,
            recent_cycles=recent_cycles,
            exit_reason_counts=exit_reason_counts,
            logic_change_ts=logic_change_ts,
        )

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved: {output_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
