#!/usr/bin/env python3
"""Crypto trigger batch for Phase 1 candidate selection.

This module builds trigger-based crypto candidates and outputs final symbols
with risk metrics (target/stop/risk-reward) in JSON.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv():
        return False

load_dotenv()

import argparse
import datetime as dt
import json
import logging
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from crypto.theme_classifier import classify_symbol_theme

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
logger.addHandler(_handler)


DEFAULT_SYMBOLS = [
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
    "MATIC-USD",
    "UNI-USD",
    "LTC-USD",
    "BCH-USD",
    "ATOM-USD",
    "NEAR-USD",
]

DEFAULT_FALLBACK_MAX_ENTRIES = 1


def _ema(series: pd.Series, window: int) -> pd.Series:
    return series.ewm(span=window, adjust=False).mean()


def _atr_percent(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(period).mean()
    return (atr / close).replace([np.inf, -np.inf], np.nan)


def _normalize_score(df: pd.DataFrame, cols: List[Tuple[str, float]]) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)

    score = pd.Series(0.0, index=df.index)
    weight_sum = sum(weight for _, weight in cols) or 1.0

    for col, weight in cols:
        col_data = df[col].astype(float)
        col_min = col_data.min()
        col_max = col_data.max()
        col_range = col_max - col_min if col_max > col_min else 1.0
        normalized = (col_data - col_min) / col_range
        score += normalized * weight

    return score / weight_sum


def fetch_symbol_bars(symbol: str, period: str, interval: str) -> pd.DataFrame:
    """Fetch OHLCV bars and return a normalized DataFrame."""
    # Retry with fallback period/interval pairs for better data stability.
    query_plan = [
        (period, interval),
        ("30d", "1h"),
        ("60d", "1d"),
    ]

    hist = pd.DataFrame()
    last_error = None
    for p, i in query_plan:
        for attempt in range(3):
            try:
                hist = yf.Ticker(symbol).history(period=p, interval=i, auto_adjust=False)
                if isinstance(hist, pd.DataFrame) and not hist.empty:
                    break
            except Exception as exc:
                last_error = exc
            time.sleep(0.35 * (attempt + 1))
        if isinstance(hist, pd.DataFrame) and not hist.empty:
            break

    if hist.empty:
        if last_error is not None:
            logger.warning("Price fetch failed for %s after retries: %s", symbol, last_error)
        else:
            logger.warning("Price fetch failed for %s after retries: empty response", symbol)
        return pd.DataFrame()
    if hist.empty:
        return pd.DataFrame()

    bars = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    bars.dropna(inplace=True)
    if bars.empty:
        return pd.DataFrame()

    bars["Amount"] = bars["Close"] * bars["Volume"]
    bars["EMA20"] = _ema(bars["Close"], 20)
    bars["EMA50"] = _ema(bars["Close"], 50)
    bars["ATR_PCT"] = _atr_percent(bars, 14)
    return bars


def build_snapshot(symbols: List[str], period: str, interval: str) -> pd.DataFrame:
    """Build one-row-per-symbol snapshot with derived features."""
    records: List[Dict[str, float]] = []

    for symbol in symbols:
        bars = fetch_symbol_bars(symbol, period=period, interval=interval)
        if bars.empty or len(bars) < 60:
            logger.debug("Skipping %s due to insufficient bars", symbol)
            continue

        last = bars.iloc[-1]
        prev = bars.iloc[-2]
        prev4 = bars.iloc[-5] if len(bars) >= 5 else prev
        vol_mean20 = bars["Volume"].tail(20).mean()
        atr_pct_mean20 = bars["ATR_PCT"].tail(20).mean()
        range_high20 = bars["High"].iloc[-21:-1].max()

        ret_1 = (last["Close"] / prev["Close"] - 1.0) * 100.0 if prev["Close"] > 0 else 0.0
        ret_4 = (last["Close"] / prev4["Close"] - 1.0) * 100.0 if prev4["Close"] > 0 else 0.0
        volume_ratio = last["Volume"] / vol_mean20 if vol_mean20 > 0 else 0.0
        atr_pct = float(last["ATR_PCT"]) if pd.notna(last["ATR_PCT"]) else 0.0
        atr_expansion = (atr_pct / atr_pct_mean20) if atr_pct_mean20 and not np.isnan(atr_pct_mean20) else 0.0
        trend_gap = (last["EMA20"] / last["EMA50"] - 1.0) * 100.0 if last["EMA50"] > 0 else 0.0
        breakout_pct = (last["Close"] / range_high20 - 1.0) * 100.0 if range_high20 and range_high20 > 0 else -999.0

        records.append(
            {
                "symbol": symbol,
                "close": float(last["Close"]),
                "volume": float(last["Volume"]),
                "amount": float(last["Amount"]),
                "ret_1_pct": float(ret_1),
                "ret_4_pct": float(ret_4),
                "volume_ratio_20": float(volume_ratio),
                "atr_pct": float(atr_pct),
                "atr_expansion": float(atr_expansion),
                "trend_gap_pct": float(trend_gap),
                "breakout_pct": float(breakout_pct),
                "ema20_gt_ema50": bool(last["EMA20"] > last["EMA50"]),
                "theme": classify_symbol_theme(symbol),
            }
        )

    if not records:
        return pd.DataFrame()
    return pd.DataFrame.from_records(records).set_index("symbol")


def trigger_volume_momentum(snapshot: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Trigger 1: Volume surge with short-term momentum."""
    if snapshot.empty:
        return pd.DataFrame()

    df = snapshot.copy()
    cond = (
        (df["volume_ratio_20"] >= 1.8)
        & (df["ret_1_pct"] >= 0.8)
        & (df["ema20_gt_ema50"])
    )
    df = df[cond]
    if df.empty:
        return df

    df["composite_score"] = _normalize_score(
        df,
        cols=[
            ("volume_ratio_20", 0.45),
            ("ret_1_pct", 0.35),
            ("amount", 0.20),
        ],
    )
    return df.sort_values("composite_score", ascending=False).head(top_n)


def trigger_volatility_trend(snapshot: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Trigger 2: Volatility expansion with trend alignment."""
    if snapshot.empty:
        return pd.DataFrame()

    df = snapshot.copy()
    cond = (
        (df["atr_expansion"] >= 1.15)
        & (df["ret_4_pct"] >= 1.2)
        & (df["ema20_gt_ema50"])
    )
    df = df[cond]
    if df.empty:
        return df

    df["composite_score"] = _normalize_score(
        df,
        cols=[
            ("atr_expansion", 0.40),
            ("trend_gap_pct", 0.35),
            ("amount", 0.25),
        ],
    )
    return df.sort_values("composite_score", ascending=False).head(top_n)


def trigger_range_breakout(snapshot: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Trigger 3: Range breakout with supporting volume."""
    if snapshot.empty:
        return pd.DataFrame()

    df = snapshot.copy()
    cond = (
        (df["breakout_pct"] >= 0.1)
        & (df["volume_ratio_20"] >= 1.5)
        & (df["ret_1_pct"] >= 0.0)
    )
    df = df[cond]
    if df.empty:
        return df

    df["composite_score"] = _normalize_score(
        df,
        cols=[
            ("breakout_pct", 0.45),
            ("volume_ratio_20", 0.35),
            ("amount", 0.20),
        ],
    )
    return df.sort_values("composite_score", ascending=False).head(top_n)


def calculate_agent_fit_metrics(row: pd.Series) -> Dict[str, float]:
    """Compute stop/target/risk-reward and agent-fit score."""
    price = float(row["close"])
    atr_pct = max(float(row.get("atr_pct", 0.0)), 0.0)
    volume_ratio = max(float(row.get("volume_ratio_20", 0.0)), 0.0)

    stop_loss_pct = float(np.clip(1.2 * atr_pct, 0.02, 0.06))
    target_pct = max(2.0 * stop_loss_pct, 0.05)
    risk_reward_ratio = target_pct / stop_loss_pct if stop_loss_pct > 0 else 0.0

    stop_loss_price = price * (1.0 - stop_loss_pct)
    target_price = price * (1.0 + target_pct)

    rr_score = min(risk_reward_ratio / 2.0, 1.0)
    liq_score = min(volume_ratio / 2.5, 1.0)
    agent_fit_score = rr_score * 0.65 + liq_score * 0.35

    return {
        "stop_loss_price": stop_loss_price,
        "target_price": target_price,
        "stop_loss_pct": stop_loss_pct,
        "target_pct": target_pct,
        "risk_reward_ratio": risk_reward_ratio,
        "agent_fit_score": agent_fit_score,
    }


def score_candidates_by_agent_criteria(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    metrics = out.apply(calculate_agent_fit_metrics, axis=1, result_type="expand")
    return pd.concat([out, metrics], axis=1)


def select_final_symbols(
    triggers: Dict[str, pd.DataFrame],
    use_hybrid: bool = True,
    max_positions: int = 3,
) -> Dict[str, pd.DataFrame]:
    """Select final symbols from trigger candidates."""
    trigger_candidates: Dict[str, pd.DataFrame] = {}

    for name, df in triggers.items():
        if df.empty:
            continue
        scored = score_candidates_by_agent_criteria(df)
        if use_hybrid:
            score_norm = _normalize_score(scored, cols=[("composite_score", 1.0)])
            scored["composite_score_norm"] = score_norm
            scored["final_score"] = scored["composite_score_norm"] * 0.3 + scored["agent_fit_score"] * 0.7
            scored = scored.sort_values("final_score", ascending=False)
        else:
            scored["final_score"] = scored["composite_score"]
            scored = scored.sort_values("composite_score", ascending=False)
        trigger_candidates[name] = scored

    if not trigger_candidates:
        return {}

    final: Dict[str, pd.DataFrame] = {}
    selected: set[str] = set()

    # First pass: one unique symbol per trigger.
    for trigger_name, df in trigger_candidates.items():
        for symbol in df.index:
            if symbol in selected:
                continue
            final[trigger_name] = df.loc[[symbol]]
            selected.add(symbol)
            break
        if len(selected) >= max_positions:
            return final

    # Second pass: fill by global final_score.
    pool: List[Tuple[str, str, float]] = []
    for trigger_name, df in trigger_candidates.items():
        for symbol in df.index:
            if symbol in selected:
                continue
            pool.append((trigger_name, symbol, float(df.loc[symbol, "final_score"])))
    pool.sort(key=lambda x: x[2], reverse=True)

    for trigger_name, symbol, _ in pool:
        if len(selected) >= max_positions:
            break
        if symbol in selected:
            continue
        if trigger_name in final:
            final[trigger_name] = pd.concat([final[trigger_name], trigger_candidates[trigger_name].loc[[symbol]]])
        else:
            final[trigger_name] = trigger_candidates[trigger_name].loc[[symbol]]
        selected.add(symbol)

    return final


def fallback_candidates(snapshot: pd.DataFrame, top_n: int = 3) -> pd.DataFrame:
    """Fallback candidate selector when all strict triggers are empty."""
    if snapshot.empty:
        return pd.DataFrame()

    df = snapshot.copy()
    # Prefer trend-aligned and sufficiently liquid symbols first.
    preferred = df[(df["ema20_gt_ema50"]) & (df["volume_ratio_20"] >= 0.9)].copy()
    if preferred.empty:
        preferred = df.copy()

    preferred["composite_score"] = _normalize_score(
        preferred,
        cols=[
            ("amount", 0.45),
            ("volume_ratio_20", 0.25),
            ("ret_4_pct", 0.20),
            ("trend_gap_pct", 0.10),
        ],
    )
    return preferred.sort_values("composite_score", ascending=False).head(top_n)


def _build_output(final_results: Dict[str, pd.DataFrame], metadata: Dict[str, str]) -> Dict:
    output: Dict[str, object] = {}

    for trigger_name, df in final_results.items():
        if df.empty:
            continue
        items = []
        for symbol in df.index:
            r = df.loc[symbol]
            items.append(
                {
                    "symbol": symbol,
                    "current_price": float(r["close"]),
                    "volume": float(r["volume"]),
                    "trade_value": float(r["amount"]),
                    "ret_1_pct": float(r["ret_1_pct"]),
                    "ret_4_pct": float(r["ret_4_pct"]),
                    "volume_ratio_20": float(r["volume_ratio_20"]),
                    "atr_pct": float(r["atr_pct"]),
                    "risk_reward_ratio": float(r["risk_reward_ratio"]),
                    "theme": str(r.get("theme", "Other")),
                    "stop_loss_pct": float(r["stop_loss_pct"]) * 100.0,
                    "stop_loss_price": float(r["stop_loss_price"]),
                    "target_pct": float(r["target_pct"]) * 100.0,
                    "target_price": float(r["target_price"]),
                    "agent_fit_score": float(r["agent_fit_score"]),
                    "composite_score": float(r["composite_score"]),
                    "final_score": float(r["final_score"]),
                }
            )
        output[trigger_name] = items

    output["metadata"] = metadata
    return output


def run_batch(
    symbols: List[str],
    interval: str = "1h",
    period: str = "14d",
    max_positions: int = 3,
    fallback_max_entries: int = DEFAULT_FALLBACK_MAX_ENTRIES,
    log_level: str = "INFO",
    output_file: str | None = None,
) -> Dict:
    """Run trigger batch and optionally write JSON output."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(numeric_level)
    _handler.setLevel(numeric_level)

    logger.info("Crypto trigger batch started: interval=%s period=%s symbols=%d", interval, period, len(symbols))
    snapshot = build_snapshot(symbols, period=period, interval=interval)
    if snapshot.empty:
        logger.warning("No valid snapshot data.")
        return {"metadata": {"status": "empty"}}

    triggers = {
        "Volume Momentum": trigger_volume_momentum(snapshot, top_n=10),
        "Volatility Trend Expansion": trigger_volatility_trend(snapshot, top_n=10),
        "Range Breakout": trigger_range_breakout(snapshot, top_n=10),
    }

    for name, df in triggers.items():
        logger.info("%s candidates: %d", name, len(df))

    final_results = select_final_symbols(triggers, use_hybrid=True, max_positions=max_positions)
    if not final_results:
        fallback_limit = max(1, min(max_positions, fallback_max_entries))
        fb = fallback_candidates(snapshot, top_n=fallback_limit)
        if not fb.empty:
            logger.info(
                "All strict triggers empty. Applying fallback selector with %d candidates (limit=%d).",
                len(fb),
                fallback_limit,
            )
            final_results = select_final_symbols(
                {"Fallback Momentum": fb},
                use_hybrid=True,
                max_positions=fallback_limit,
            )

    metadata = {
        "run_time": dt.datetime.utcnow().isoformat() + "Z",
        "market": "CRYPTO",
        "interval": interval,
        "period": period,
        "universe_size": str(len(symbols)),
        "selection_mode": "hybrid",
        "max_positions": str(max_positions),
        "fallback_max_entries": str(max(1, min(max_positions, fallback_max_entries))),
    }
    output = _build_output(final_results, metadata)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        logger.info("Saved output JSON: %s", output_file)

    return output


def _parse_symbols(raw: str) -> List[str]:
    symbols = [x.strip().upper() for x in raw.split(",") if x.strip()]
    return symbols or DEFAULT_SYMBOLS


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run crypto trigger batch.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated symbols (e.g. BTC-USD,ETH-USD)")
    parser.add_argument("--interval", default="1h", help="Bar interval (e.g. 15m,30m,1h,4h,1d)")
    parser.add_argument("--period", default="14d", help="History period (e.g. 7d,14d,30d,60d)")
    parser.add_argument("--max-positions", type=int, default=3, help="Maximum final selections")
    parser.add_argument("--fallback-max-entries", type=int, default=DEFAULT_FALLBACK_MAX_ENTRIES, help="Max entries when strict triggers are empty")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    parser.add_argument("--output", help="Optional output json file path")
    args = parser.parse_args()

    run_batch(
        symbols=_parse_symbols(args.symbols),
        interval=args.interval,
        period=args.period,
        max_positions=args.max_positions,
        fallback_max_entries=args.fallback_max_entries,
        log_level=args.log_level,
        output_file=args.output,
    )


