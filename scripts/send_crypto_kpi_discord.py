#!/usr/bin/env python3
"""Send daily crypto KPI summary to Discord via OpenClaw."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


DEFAULT_BENCHMARK_JSON = "examples/dashboard/public/crypto_benchmark_data.json"
DEFAULT_SESSIONS_JSON = "/home/jinny/.openclaw/agents/main/sessions/sessions.json"
DEFAULT_OPENCLAW_NODE = "/home/jinny/.local/node/node-v22.12.0-linux-x64/bin/node"
DEFAULT_OPENCLAW_CLI = "/home/jinny/.local/node/node-v22.12.0-linux-x64/lib/node_modules/openclaw/openclaw.mjs"


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_pct(v: float, signed: bool = True) -> str:
    if signed:
        return f"{v:+.2f}%"
    return f"{v:.2f}%"


def _fmt_ratio(v: Optional[float]) -> str:
    if v is None:
        return "-"
    return f"{v:.2f}"


def detect_discord_target_from_sessions(sessions_path: Path) -> Optional[str]:
    if not sessions_path.exists():
        return None
    try:
        obj = _load_json(sessions_path)
    except Exception:
        return None

    best: Tuple[int, Optional[str]] = (-1, None)
    for _, session in obj.items():
        if not isinstance(session, dict):
            continue
        last_channel = str(session.get("lastChannel") or "").lower()
        last_to = str(session.get("lastTo") or "")
        updated_at = int(session.get("updatedAt") or 0)

        if last_channel == "discord" and last_to:
            if updated_at > best[0]:
                best = (updated_at, last_to)
            continue

        key = str(session.get("key") or "")
        # fallback: parse key pattern like agent:main:discord:channel:147...
        marker = ":discord:channel:"
        if marker in key:
            channel_id = key.split(marker, 1)[1].split(":", 1)[0]
            candidate = f"channel:{channel_id}" if channel_id else None
            if candidate and updated_at > best[0]:
                best = (updated_at, candidate)

    return best[1]


def build_message(data: Dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    kpi = summary.get("kpi") or {}
    recent = kpi.get("recent_24h") or {}
    targets = kpi.get("targets") or {}
    passes = kpi.get("passes") or {}

    algo_ret = float(summary.get("algorithm_return_pct") or 0.0)
    btc_ret = float(summary.get("btc_return_pct") or 0.0)
    uni_ret = float(summary.get("universe_return_pct") or 0.0)

    downside_btc = kpi.get("downside_capture_vs_btc")
    downside_uni = kpi.get("downside_capture_vs_universe")
    rot_ratio = float(recent.get("rotation_buy_ratio") or 0.0) * 100.0
    cost_adj = float(recent.get("cost_adjusted_avg_trade_pct") or 0.0)
    roundtrip = float(recent.get("roundtrip_cost_pct") or 0.0)
    buys = int(recent.get("buys") or 0)
    rot_buys = int(recent.get("rotation_buys") or 0)
    sells = int(recent.get("sells") or 0)
    win_rate = float(recent.get("win_rate") or 0.0)

    overall = "PASS" if bool(passes.get("overall")) else "FAIL"
    generated_at = str(data.get("generated_at") or "-")
    window_days = int(kpi.get("window_days") or 0)
    down_target = float(targets.get("downside_capture_max") or 0.9)
    rot_target = float(targets.get("rotation_buy_ratio_max") or 0.35) * 100.0

    lines = [
        f"[Crypto KPI Daily 09:00] {overall}",
        f"Generated: {generated_at} (window: {window_days}d)",
        f"Return: Algo {_fmt_pct(algo_ret)} | BTC {_fmt_pct(btc_ret)} | Universe {_fmt_pct(uni_ret)}",
        f"Downside Capture: BTC {_fmt_ratio(downside_btc)} / Uni {_fmt_ratio(downside_uni)} (target <= {down_target:.2f})",
        f"24h Rotation Buy Ratio: {rot_ratio:.2f}% (target <= {rot_target:.2f}%)",
        f"24h Cost-Adjusted Avg Trade: {_fmt_pct(cost_adj)} (roundtrip cost {roundtrip:.2f}%)",
        f"24h Flow: buys {buys} (rotation {rot_buys}), sells {sells}, win {win_rate:.2f}%",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Send daily KPI report to Discord via OpenClaw.")
    parser.add_argument("--benchmark-json", default=DEFAULT_BENCHMARK_JSON)
    parser.add_argument("--sessions-json", default=DEFAULT_SESSIONS_JSON)
    parser.add_argument("--channel", default="discord")
    parser.add_argument("--target", default="")
    parser.add_argument("--account", default="default")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--openclaw-node", default=DEFAULT_OPENCLAW_NODE)
    parser.add_argument("--openclaw-cli", default=DEFAULT_OPENCLAW_CLI)
    args = parser.parse_args()

    benchmark_path = Path(args.benchmark_json)
    if not benchmark_path.exists():
        raise SystemExit(f"Benchmark JSON not found: {benchmark_path}")

    data = _load_json(benchmark_path)
    message = build_message(data)

    target = args.target.strip() or os.getenv("OPENCLAW_DISCORD_TARGET", "").strip()
    if not target:
        target = detect_discord_target_from_sessions(Path(args.sessions_json)) or ""
    if not target:
        raise SystemExit("Discord target not found. Set --target or OPENCLAW_DISCORD_TARGET.")

    cmd = [
        args.openclaw_node,
        args.openclaw_cli,
        "message",
        "send",
        "--channel",
        args.channel,
        "--target",
        target,
        "--account",
        args.account,
        "--message",
        message,
        "--json",
    ]
    if args.dry_run:
        cmd.append("--dry-run")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    print(f"target={target}")
    if proc.stdout:
        print(proc.stdout.strip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.strip())
        return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

