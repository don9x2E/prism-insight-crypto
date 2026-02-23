#!/usr/bin/env python3
"""Summarize recent cycle quality metrics for 24h and prior 24h windows."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta


def _safe_float(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _window_metrics(cur: sqlite3.Cursor, start_ts: str, end_ts: str) -> dict:
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN side = 'buy' AND status = 'filled' THEN 1 ELSE 0 END) AS buys,
            SUM(CASE WHEN side = 'buy' AND status = 'filled' AND metadata LIKE '%rotation%' THEN 1 ELSE 0 END) AS rotation_buys,
            SUM(CASE WHEN side = 'sell' AND status = 'filled' THEN 1 ELSE 0 END) AS sells
        FROM crypto_order_executions
        WHERE created_at >= ? AND created_at < ?
        """,
        (start_ts, end_ts),
    )
    row = cur.fetchone()
    buys = int((row[0] or 0))
    rotation_buys = int((row[1] or 0))
    sells = int((row[2] or 0))

    cur.execute(
        """
        SELECT
            AVG(holding_hours),
            AVG(profit_rate),
            SUM(profit_rate)
        FROM crypto_trading_history
        WHERE sell_date >= ? AND sell_date < ?
        """,
        (start_ts, end_ts),
    )
    row2 = cur.fetchone()
    avg_holding_hours = _safe_float(row2[0])
    avg_profit_rate = _safe_float(row2[1])
    sum_profit_rate = _safe_float(row2[2])

    return {
        "buys": buys,
        "rotation_buys": rotation_buys,
        "sells": sells,
        "avg_holding_hours": avg_holding_hours,
        "avg_profit_rate": avg_profit_rate,
        "sum_profit_rate": sum_profit_rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit 24h-vs-prior24h cycle quality metrics.")
    parser.add_argument("--db-path", default="stock_tracking_db.sqlite")
    parser.add_argument("--roundtrip-cost-pct", type=float, default=0.3, help="Estimated all-in roundtrip cost percent")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    cur = conn.cursor()

    now = datetime.now()
    recent_start = now - timedelta(hours=24)
    prior_start = now - timedelta(hours=48)

    now_ts = now.strftime("%Y-%m-%d %H:%M:%S")
    recent_start_ts = recent_start.strftime("%Y-%m-%d %H:%M:%S")
    prior_start_ts = prior_start.strftime("%Y-%m-%d %H:%M:%S")

    recent = _window_metrics(cur, recent_start_ts, now_ts)
    prior = _window_metrics(cur, prior_start_ts, recent_start_ts)

    def _edge(avg_profit_rate: float) -> float:
        return avg_profit_rate - args.roundtrip_cost_pct

    print("Cycle Metrics (recent24h vs prior24h)")
    print(
        "recent24h: buys={buys}, rotation_buys={rotation_buys}, sells={sells}, "
        "avg_hold_h={avg_holding_hours:.2f}, avg_profit={avg_profit_rate:.2f}%, "
        "avg_edge_after_cost={edge:.2f}%".format(
            edge=_edge(recent["avg_profit_rate"]),
            **recent,
        )
    )
    print(
        "prior24h: buys={buys}, rotation_buys={rotation_buys}, sells={sells}, "
        "avg_hold_h={avg_holding_hours:.2f}, avg_profit={avg_profit_rate:.2f}%, "
        "avg_edge_after_cost={edge:.2f}%".format(
            edge=_edge(prior["avg_profit_rate"]),
            **prior,
        )
    )
    print(
        "delta(recent-prior): buys={buys_d:+d}, rotation_buys={rot_d:+d}, sells={sells_d:+d}, "
        "avg_hold_h={hold_d:+.2f}, avg_profit={pnl_d:+.2f}%".format(
            buys_d=recent["buys"] - prior["buys"],
            rot_d=recent["rotation_buys"] - prior["rotation_buys"],
            sells_d=recent["sells"] - prior["sells"],
            hold_d=recent["avg_holding_hours"] - prior["avg_holding_hours"],
            pnl_d=recent["avg_profit_rate"] - prior["avg_profit_rate"],
        )
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

