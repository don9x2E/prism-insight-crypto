#!/usr/bin/env python3
"""Crypto Tracking Agent (Phase 2).

Reads Phase 1 candidate JSON, generates entry scenarios via LLM,
and persists entry/no_entry decisions into crypto tables.
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional dependency
    def load_dotenv():
        return False

load_dotenv()

import asyncio
import json
import logging
import os
import sqlite3
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from mcp_agent.workflows.llm.augmented_llm import RequestParams
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM

from crypto.cores.agents.trading_agents import create_crypto_trading_scenario_agent
from crypto.trading import PaperCryptoTrading
from crypto.theme_classifier import classify_symbol_theme
from crypto.tracking import (
    add_theme_columns_if_missing,
    create_crypto_indexes,
    create_crypto_tables,
    get_crypto_holdings_count,
    is_crypto_symbol_in_holdings,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"crypto_tracking_{datetime.now().strftime('%Y%m%d')}.log"),
    ],
)
logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _parse_json_object(text: str) -> Dict[str, Any]:
    """Best-effort JSON parser for LLM output."""
    if not text:
        return {}
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            return json.loads(stripped)
        except Exception:
            pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(stripped[start : end + 1])
        except Exception:
            pass
    return {}


def _parse_scenario_field(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        return _parse_json_object(value)
    return {}


def default_scenario() -> Dict[str, Any]:
    return {
        "buy_score": 0,
        "min_score": 6,
        "decision": "no_entry",
        "target_price": 0,
        "stop_loss": 0,
        "risk_reward_ratio": 0,
        "expected_return_pct": 0,
        "expected_loss_pct": 0,
        "investment_period": "short",
        "rationale": "Analysis failed",
        "theme": "Major",
        "market_condition": "sideways",
        "trading_scenarios": {
            "key_levels": {},
            "sell_triggers": [],
            "hold_conditions": [],
            "portfolio_context": "",
        },
    }


class CryptoTrackingAgent:
    """Phase 2 crypto decision and persistence agent."""

    MAX_SLOTS = 10
    ROTATION_MIN_SCORE_DELTA = 0.12
    ROTATION_LOSS_PRIORITY_PCT = -2.0
    ROTATION_MAX_PER_CYCLE = 1
    ROTATION_MIN_HOLDING_HOURS = 4.0
    ROTATION_REENTRY_COOLDOWN_HOURS = 0.0

    def __init__(
        self,
        db_path: str = "stock_tracking_db.sqlite",
        language: str = "ko",
        timeframe: str = "1h",
        execute_trades: bool = False,
        trade_mode: str = "paper",
        quote_amount: float = 100.0,
        rotation_reentry_cooldown_hours: float = ROTATION_REENTRY_COOLDOWN_HOURS,
    ):
        self.db_path = db_path
        self.language = language
        self.timeframe = timeframe
        self.max_slots = self.MAX_SLOTS
        self.execute_trades = execute_trades
        self.trade_mode = trade_mode
        self.quote_amount = quote_amount
        self.rotation_reentry_cooldown_hours = max(0.0, float(rotation_reentry_cooldown_hours))

        self.conn: sqlite3.Connection | None = None
        self.cursor: sqlite3.Cursor | None = None
        self.trading_agent = None
        self.paper_trader: PaperCryptoTrading | None = None
        self._cycle_exit_counts = {"stop_loss": 0, "rotation": 0, "normal": 0}

    async def initialize(self) -> bool:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        create_crypto_tables(self.cursor, self.conn)
        create_crypto_indexes(self.cursor, self.conn)
        add_theme_columns_if_missing(self.cursor, self.conn)
        self.trading_agent = create_crypto_trading_scenario_agent(language=self.language)
        if self.execute_trades and self.trade_mode == "paper":
            self.paper_trader = PaperCryptoTrading(self.cursor, self.conn)
            logger.info("Paper trading adapter enabled (quote_amount=%.2f)", self.quote_amount)
        logger.info(
            "CryptoTrackingAgent initialized (rotation_reentry_cooldown_hours=%.2f)",
            self.rotation_reentry_cooldown_hours,
        )
        return True

    async def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cursor = None

    def _get_live_price(self, symbol: str, fallback_price: float = 0.0) -> float:
        """Get latest price using paper adapter when available."""
        try:
            if self.paper_trader:
                p = _safe_float(self.paper_trader.get_current_price(symbol), 0.0)
                if p > 0:
                    return p
        except Exception:
            pass
        return fallback_price

    def _build_prompt(self, symbol: str, trigger_type: str, candidate: Dict[str, Any]) -> str:
        return f"""
다음은 코인 후보 데이터입니다. 매매 시나리오 JSON을 생성하세요.

[Candidate]
- Symbol: {symbol}
- Trigger: {trigger_type}
- Current Price: {candidate.get("current_price")}
- 1h Return (%): {candidate.get("ret_1_pct")}
- 4h Return (%): {candidate.get("ret_4_pct")}
- Volume Ratio(20): {candidate.get("volume_ratio_20")}
- ATR (%): {candidate.get("atr_pct")}
- Phase1 Risk-Reward: {candidate.get("risk_reward_ratio")}
- Phase1 Target: {candidate.get("target_price")}
- Phase1 Stop: {candidate.get("stop_loss_price")}
- Phase1 Final Score: {candidate.get("final_score")}
- Theme: {candidate.get("theme")}

요구사항:
- 보수적으로 판단.
- decision은 반드시 entry/no_entry 중 하나.
- 숫자 필드는 숫자만.
"""

    def _heuristic_scenario(self, symbol: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
        """Fallback scenario when LLM is unavailable (e.g., no API key)."""
        price = _safe_float(candidate.get("current_price"), 0.0)
        target = _safe_float(candidate.get("target_price"), price * 1.05 if price > 0 else 0.0)
        stop = _safe_float(candidate.get("stop_loss_price"), price * 0.96 if price > 0 else 0.0)
        rr = _safe_float(candidate.get("risk_reward_ratio"), 0.0)
        final_score = _safe_float(candidate.get("final_score"), 0.0)
        decision = "entry" if (rr >= 1.6 and final_score >= 0.45) else "no_entry"
        buy_score = int(max(1, min(10, round(final_score * 10))))
        min_score = 5
        expected_return_pct = ((target - price) / price * 100.0) if price > 0 else 0.0
        expected_loss_pct = ((price - stop) / price * 100.0) if price > 0 else 0.0

        return {
            "buy_score": buy_score,
            "min_score": min_score,
            "decision": decision,
            "target_price": target,
            "stop_loss": stop,
            "risk_reward_ratio": rr,
            "expected_return_pct": expected_return_pct,
            "expected_loss_pct": expected_loss_pct,
            "investment_period": "short",
            "rationale": "Heuristic fallback scenario (LLM unavailable).",
            "theme": candidate.get("theme", classify_symbol_theme(symbol)),
            "market_condition": "sideways",
            "trading_scenarios": {
                "key_levels": {
                    "primary_support": stop,
                    "secondary_support": stop * 0.98 if stop > 0 else 0,
                    "primary_resistance": target,
                    "secondary_resistance": target * 1.02 if target > 0 else 0,
                    "volume_baseline": "20-bar average volume",
                },
                "sell_triggers": [
                    "Stop loss reached",
                    "Target reached",
                    "Time-based exit after momentum fade",
                ],
                "hold_conditions": [
                    "Price remains above support",
                    "Volume not collapsing",
                ],
                "portfolio_context": "Fallback mode",
            },
        }

    async def analyze_candidate(self, symbol: str, trigger_type: str, candidate: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if not self.trading_agent:
                raise RuntimeError("Trading agent not initialized")

            if not os.environ.get("OPENAI_API_KEY"):
                logger.warning("OPENAI_API_KEY not found. Using heuristic scenario for %s", symbol)
                return self._heuristic_scenario(symbol, candidate)

            llm = await self.trading_agent.attach_llm(OpenAIAugmentedLLM)
            response = await llm.generate_str(
                message=self._build_prompt(symbol, trigger_type, candidate),
                request_params=RequestParams(model="gpt-5-nano", maxTokens=4000),
            )
            parsed = _parse_json_object(response)
            if not parsed:
                logger.warning("Failed to parse scenario JSON for %s, fallback to default", symbol)
                parsed = default_scenario()

            # Normalize/fill using phase1 metrics when missing.
            parsed.setdefault("buy_score", 0)
            parsed.setdefault("min_score", 6)
            parsed.setdefault("decision", "no_entry")
            parsed["decision"] = str(parsed["decision"]).strip().lower()
            if parsed["decision"] not in ("entry", "no_entry"):
                parsed["decision"] = "no_entry"

            parsed["target_price"] = _safe_float(parsed.get("target_price"), _safe_float(candidate.get("target_price"), 0.0))
            parsed["stop_loss"] = _safe_float(parsed.get("stop_loss"), _safe_float(candidate.get("stop_loss_price"), 0.0))
            parsed["risk_reward_ratio"] = _safe_float(
                parsed.get("risk_reward_ratio"),
                _safe_float(candidate.get("risk_reward_ratio"), 0.0),
            )
            parsed["expected_return_pct"] = _safe_float(parsed.get("expected_return_pct"), _safe_float(candidate.get("target_pct"), 0.0))
            parsed["expected_loss_pct"] = _safe_float(parsed.get("expected_loss_pct"), _safe_float(candidate.get("stop_loss_pct"), 0.0))
            parsed.setdefault("theme", "Major")
            if not parsed.get("theme"):
                parsed["theme"] = classify_symbol_theme(symbol)
            parsed.setdefault("investment_period", "short")
            parsed.setdefault("market_condition", "sideways")
            parsed.setdefault("rationale", "No rationale")
            parsed.setdefault("trading_scenarios", {})
            return parsed
        except Exception as e:
            logger.error("Error analyzing candidate %s: %s", symbol, e)
            logger.error(traceback.format_exc())
            return self._heuristic_scenario(symbol, candidate)

    async def _save_watchlist(
        self,
        symbol: str,
        trigger_type: str,
        candidate: Dict[str, Any],
        scenario: Dict[str, Any],
        reason: str,
    ):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            """
            INSERT INTO crypto_watchlist_history
            (symbol, analyzed_date, current_price, buy_score, min_score, decision, skip_reason,
             target_price, stop_loss, risk_reward_ratio, trigger_type, timeframe, theme, scenario)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                now,
                _safe_float(candidate.get("current_price"), 0.0),
                int(_safe_float(scenario.get("buy_score"), 0)),
                int(_safe_float(scenario.get("min_score"), 0)),
                "no_entry",
                reason,
                _safe_float(scenario.get("target_price"), 0.0),
                _safe_float(scenario.get("stop_loss"), 0.0),
                _safe_float(scenario.get("risk_reward_ratio"), 0.0),
                trigger_type,
                self.timeframe,
                scenario.get("theme", classify_symbol_theme(symbol)),
                json.dumps(scenario, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    async def _save_holding(
        self,
        symbol: str,
        trigger_type: str,
        candidate: Dict[str, Any],
        scenario: Dict[str, Any],
        execution: Dict[str, Any] | None = None,
    ):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fallback_price = _safe_float(candidate.get("current_price"), 0.0)
        exec_price = _safe_float((execution or {}).get("executed_price"), fallback_price)
        exec_qty = _safe_float((execution or {}).get("quantity"), 0.0)
        exec_notional = _safe_float((execution or {}).get("quote_amount"), 0.0)
        # Persist phase1 scoring context to support slot rotation decisions.
        scenario_with_phase1 = dict(scenario)
        scenario_with_phase1.setdefault("phase1_final_score", _safe_float(candidate.get("final_score"), 0.0))
        scenario_with_phase1.setdefault("phase1_composite_score", _safe_float(candidate.get("composite_score"), 0.0))
        scenario_with_phase1.setdefault("phase1_risk_reward_ratio", _safe_float(candidate.get("risk_reward_ratio"), 0.0))
        scenario_with_phase1.setdefault("phase1_volume_ratio_20", _safe_float(candidate.get("volume_ratio_20"), 0.0))

        asset_name = symbol.split("-")[0].upper()
        self.cursor.execute(
            """
            INSERT INTO crypto_holdings
            (symbol, asset_name, buy_price, buy_date, quantity, notional_usd, current_price,
             last_updated, scenario, target_price, stop_loss, trigger_type, timeframe, theme)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                asset_name,
                exec_price,
                now,
                exec_qty if exec_qty > 0 else None,
                exec_notional if exec_notional > 0 else None,
                exec_price if exec_price > 0 else fallback_price,
                now,
                json.dumps(scenario_with_phase1, ensure_ascii=False),
                _safe_float(scenario.get("target_price"), 0.0),
                _safe_float(scenario.get("stop_loss"), 0.0),
                trigger_type,
                self.timeframe,
                scenario.get("theme", "Major"),
            ),
        )
        self.conn.commit()

    async def _analyze_sell_decision(self, holding: Dict[str, Any]) -> Tuple[bool, str]:
        """Rule-based sell decision for current holdings."""
        try:
            buy_price = _safe_float(holding.get("buy_price"), 0.0)
            current_price = _safe_float(holding.get("current_price"), 0.0)
            target_price = _safe_float(holding.get("target_price"), 0.0)
            stop_loss = _safe_float(holding.get("stop_loss"), 0.0)
            buy_date = str(holding.get("buy_date") or "")
            scenario = _parse_scenario_field(holding.get("scenario"))
            trailing_active = bool(scenario.get("trailing_active", False))
            dynamic_stop = _safe_float(scenario.get("dynamic_stop_loss"), 0.0)

            if buy_price <= 0 or current_price <= 0:
                return False, "invalid price context"

            now_dt = datetime.now()
            try:
                buy_dt = datetime.strptime(buy_date, "%Y-%m-%d %H:%M:%S")
            except Exception:
                buy_dt = now_dt
            holding_hours = max((now_dt - buy_dt).total_seconds() / 3600.0, 0.0)
            profit_rate = ((current_price - buy_price) / buy_price) * 100.0

            # Priority 1: hard stop/target
            if stop_loss > 0 and current_price <= stop_loss:
                if trailing_active and dynamic_stop > 0:
                    return True, f"trailing stop reached ({current_price:.6f} <= {stop_loss:.6f})"
                return True, f"stop loss reached ({current_price:.6f} <= {stop_loss:.6f})"
            if target_price > 0 and current_price >= target_price:
                return True, f"target reached ({current_price:.6f} >= {target_price:.6f})"

            # Priority 2: universal risk/profit guards
            if profit_rate <= -5.0:
                return True, f"loss guard triggered ({profit_rate:.2f}%)"
            if holding_hours >= 72 and profit_rate >= 4.0:
                return True, f"time-based take-profit ({holding_hours:.1f}h, {profit_rate:.2f}%)"
            if holding_hours >= 168 and profit_rate < 0:
                return True, f"stale losing position cleanup ({holding_hours:.1f}h, {profit_rate:.2f}%)"

            return False, "hold"
        except Exception as e:
            logger.error("Error analyzing sell decision: %s", e)
            return False, "analysis_error"

    def _refresh_trailing_state(self, holding: Dict[str, Any]) -> Tuple[Dict[str, Any], float]:
        """Update trailing stop state and return (scenario, effective_stop_loss)."""
        scenario = _parse_scenario_field(holding.get("scenario"))
        buy_price = _safe_float(holding.get("buy_price"), 0.0)
        current_price = _safe_float(holding.get("current_price"), 0.0)
        base_stop = _safe_float(holding.get("stop_loss"), 0.0)
        if buy_price <= 0 or current_price <= 0:
            return scenario, base_stop

        # Track highest observed price since entry.
        peak = _safe_float(scenario.get("trailing_peak_price"), buy_price)
        peak = max(peak, current_price)
        scenario["trailing_peak_price"] = peak

        # Activate trailing stop after minimum profit.
        profit_rate = ((current_price - buy_price) / buy_price) * 100.0
        trailing_active = bool(scenario.get("trailing_active", False))
        if profit_rate >= 3.0:
            trailing_active = True
        scenario["trailing_active"] = trailing_active

        if not trailing_active:
            scenario["dynamic_stop_loss"] = base_stop
            return scenario, base_stop

        # Wider trail as profit expands to reduce premature exits.
        if profit_rate < 8.0:
            trail_buffer = 0.025
        elif profit_rate < 15.0:
            trail_buffer = 0.03
        else:
            trail_buffer = 0.04

        trail_stop = peak * (1.0 - trail_buffer)
        effective_stop = max(base_stop, trail_stop) if base_stop > 0 else trail_stop
        scenario["dynamic_stop_loss"] = effective_stop
        scenario["trail_buffer_pct"] = trail_buffer * 100.0
        return scenario, effective_stop

    @staticmethod
    def _classify_exit_reason(sell_reason: str) -> str:
        reason = (sell_reason or "").strip().lower()
        if "rotation replace:" in reason:
            return "rotation"
        if "stop loss" in reason or "trailing stop" in reason or "loss guard" in reason:
            return "stop_loss"
        return "normal"

    def _reset_cycle_exit_counts(self):
        self._cycle_exit_counts = {"stop_loss": 0, "rotation": 0, "normal": 0}

    def _count_exit(self, exit_category: str):
        if exit_category not in self._cycle_exit_counts:
            exit_category = "normal"
        self._cycle_exit_counts[exit_category] = self._cycle_exit_counts.get(exit_category, 0) + 1

    def _is_reentry_cooldown_active(self, symbol: str) -> Tuple[bool, str]:
        if self.rotation_reentry_cooldown_hours <= 0:
            return False, ""
        self.cursor.execute(
            """
            SELECT sell_date
            FROM crypto_trading_history
            WHERE symbol = ?
            ORDER BY sell_date DESC, id DESC
            LIMIT 1
            """,
            (symbol,),
        )
        row = self.cursor.fetchone()
        if not row or not row[0]:
            return False, ""

        try:
            last_sell_dt = datetime.strptime(str(row[0]), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return False, ""
        cooldown_until = last_sell_dt + timedelta(hours=self.rotation_reentry_cooldown_hours)
        now_dt = datetime.now()
        if now_dt < cooldown_until:
            remaining = max((cooldown_until - now_dt).total_seconds() / 3600.0, 0.0)
            return True, (
                f"re-entry cooldown active ({remaining:.2f}h remaining, "
                f"window={self.rotation_reentry_cooldown_hours:.2f}h)"
            )
        return False, ""

    async def _sell_holding(self, holding: Dict[str, Any], sell_reason: str) -> bool:
        """Execute sell (paper if enabled), then archive to history and remove holding."""
        symbol = str(holding.get("symbol") or "")
        if not symbol:
            return False

        buy_price = _safe_float(holding.get("buy_price"), 0.0)
        current_price = _safe_float(holding.get("current_price"), 0.0)
        quantity = _safe_float(holding.get("quantity"), 0.0)
        notional = _safe_float(holding.get("notional_usd"), 0.0)
        if quantity <= 0 and buy_price > 0 and notional > 0:
            quantity = notional / buy_price

        execution_price = current_price
        exit_category = self._classify_exit_reason(sell_reason)
        if self.execute_trades:
            if self.trade_mode != "paper" or not self.paper_trader:
                logger.warning("Sell skipped %s: unsupported trade mode '%s'", symbol, self.trade_mode)
                return False
            sell_res = self.paper_trader.sell_all(
                symbol=symbol,
                quantity=quantity,
                limit_price=None,
                metadata={"reason": sell_reason, "exit_category": exit_category},
            )
            if not sell_res.get("success"):
                logger.warning("Paper sell failed %s: %s", symbol, sell_res.get("message", "unknown"))
                return False
            execution_price = _safe_float(sell_res.get("executed_price"), current_price)

        buy_date = str(holding.get("buy_date") or "")
        now_dt = datetime.now()
        try:
            buy_dt = datetime.strptime(buy_date, "%Y-%m-%d %H:%M:%S")
        except Exception:
            buy_dt = now_dt
        holding_hours = max((now_dt - buy_dt).total_seconds() / 3600.0, 0.0)
        profit_rate = ((execution_price - buy_price) / buy_price) * 100.0 if buy_price > 0 else 0.0
        now = now_dt.strftime("%Y-%m-%d %H:%M:%S")

        self.cursor.execute(
            """
            INSERT INTO crypto_trading_history
            (symbol, asset_name, buy_price, buy_date, quantity, notional_usd, sell_price, sell_date,
             profit_rate, holding_hours, scenario, trigger_type, timeframe, theme)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                holding.get("asset_name", symbol.split("-")[0].upper()),
                buy_price,
                buy_date,
                quantity if quantity > 0 else None,
                notional if notional > 0 else None,
                execution_price,
                now,
                profit_rate,
                holding_hours,
                json.dumps(_parse_scenario_field(holding.get("scenario")), ensure_ascii=False),
                holding.get("trigger_type", ""),
                holding.get("timeframe", "1h"),
                holding.get("theme", "Other"),
            ),
        )

        self.cursor.execute("DELETE FROM crypto_holdings WHERE symbol = ?", (symbol,))
        self.conn.commit()
        self._count_exit(exit_category)
        logger.info(
            "SELL %s @ %.6f (buy %.6f, pnl %.2f%%, %.1fh) reason=%s exit_category=%s",
            symbol,
            execution_price,
            buy_price,
            profit_rate,
            holding_hours,
            sell_reason,
            exit_category,
        )
        return True

    async def update_holdings(self) -> int:
        """Refresh holdings and execute sell loop. Returns sold count."""
        self.cursor.execute(
            """
            SELECT symbol, asset_name, buy_price, buy_date, quantity, notional_usd, current_price,
                   scenario, target_price, stop_loss, trigger_type, timeframe, theme
            FROM crypto_holdings
            """
        )
        holdings = [dict(r) for r in self.cursor.fetchall()]
        if not holdings:
            return 0

        sold_count = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for holding in holdings:
            symbol = holding["symbol"]
            current_price = self._get_live_price(symbol, _safe_float(holding.get("current_price"), 0.0))
            holding["current_price"] = current_price
            updated_scenario, effective_stop = self._refresh_trailing_state(holding)
            holding["scenario"] = updated_scenario
            holding["stop_loss"] = effective_stop

            should_sell, reason = await self._analyze_sell_decision(holding)
            if should_sell:
                sold = await self._sell_holding(holding, reason)
                if sold:
                    sold_count += 1
            else:
                self.cursor.execute(
                    """
                    UPDATE crypto_holdings
                    SET current_price = ?, stop_loss = ?, scenario = ?, last_updated = ?
                    WHERE symbol = ?
                    """,
                    (
                        current_price,
                        _safe_float(effective_stop, 0.0) if effective_stop > 0 else None,
                        json.dumps(updated_scenario, ensure_ascii=False),
                        now,
                        symbol,
                    ),
                )
                self.conn.commit()
        return sold_count

    def _holding_final_score(self, holding: Dict[str, Any]) -> float:
        scenario = _parse_scenario_field(holding.get("scenario"))
        score = _safe_float(scenario.get("phase1_final_score"), -1.0)
        if score < 0:
            score = _safe_float(scenario.get("final_score"), -1.0)
        if score < 0:
            score = _safe_float(holding.get("risk_reward_ratio"), 0.0) / 10.0
        return score

    async def _try_rotation_entry(
        self,
        symbol: str,
        trigger_type: str,
        candidate: Dict[str, Any],
        scenario: Dict[str, Any],
        buy_score: int,
        min_score: int,
    ) -> Tuple[bool, str, int]:
        """Replace weakest holding with stronger new candidate when slots are full."""
        new_final_score = _safe_float(candidate.get("final_score"), 0.0)
        self.cursor.execute(
            """
            SELECT symbol, asset_name, buy_price, buy_date, quantity, notional_usd, current_price,
                   scenario, target_price, stop_loss, trigger_type, timeframe, theme
            FROM crypto_holdings
            """
        )
        holdings = [dict(r) for r in self.cursor.fetchall()]
        if not holdings:
            return False, "no holdings for rotation", 0

        ranked = []
        for h in holdings:
            h_score = self._holding_final_score(h)
            live_price = self._get_live_price(h["symbol"], _safe_float(h.get("current_price"), 0.0))
            buy_price = _safe_float(h.get("buy_price"), 0.0)
            profit_rate = ((live_price - buy_price) / buy_price * 100.0) if buy_price > 0 else 0.0
            buy_date = str(h.get("buy_date") or "")
            try:
                buy_dt = datetime.strptime(buy_date, "%Y-%m-%d %H:%M:%S")
            except Exception:
                buy_dt = datetime.now()
            holding_hours = max((datetime.now() - buy_dt).total_seconds() / 3600.0, 0.0)
            is_loss_priority = profit_rate <= self.ROTATION_LOSS_PRIORITY_PCT
            ranked.append((h, h_score, profit_rate, is_loss_priority, holding_hours))

        eligible = [
            x for x in ranked
            if new_final_score >= (x[1] + self.ROTATION_MIN_SCORE_DELTA)
            and x[4] >= self.ROTATION_MIN_HOLDING_HOURS
        ]
        if not eligible:
            too_fresh = [x for x in ranked if x[4] < self.ROTATION_MIN_HOLDING_HOURS]
            if too_fresh:
                freshest = min(too_fresh, key=lambda x: x[4])
                return False, (
                    f"rotation blocked: min holding {self.ROTATION_MIN_HOLDING_HOURS:.1f}h "
                    f"(freshest {freshest[0]['symbol']}={freshest[4]:.2f}h)"
                ), 0
            weakest = min(ranked, key=lambda x: x[1])
            return False, (
                f"rotation blocked: new_final={new_final_score:.3f} "
                f"< weakest+delta ({weakest[1]:.3f}+{self.ROTATION_MIN_SCORE_DELTA:.2f})"
            ), 0

        # Keep score-delta gate, then prioritize deeper losers (rotation-loss threshold first),
        # and finally weaker score among similar PnL profiles.
        eligible.sort(key=lambda x: (x[2] >= 0.0, not x[3], x[2], x[1]))
        target_holding, target_score, target_profit, _, target_hold_hours = eligible[0]
        sell_reason = (
            f"rotation replace: {target_holding['symbol']} "
            f"(score={target_score:.3f}, pnl={target_profit:.2f}%, hold={target_hold_hours:.1f}h) "
            f"-> {symbol} (score={new_final_score:.3f})"
        )

        sold = await self._sell_holding(target_holding, sell_reason)
        if not sold:
            return False, f"rotation sell failed: {target_holding['symbol']}", 0

        execution = None
        if self.execute_trades:
            if self.trade_mode != "paper":
                return False, f"unsupported trade_mode={self.trade_mode}", 1
            if not self.paper_trader:
                return False, "paper trader not initialized", 1
            execution = self.paper_trader.buy(
                symbol=symbol,
                quote_amount=self.quote_amount,
                limit_price=None,
                metadata={"trigger_type": trigger_type, "rotation": True},
            )
            if not execution.get("success"):
                return False, f"paper buy failed after rotation: {execution.get('message', 'unknown')}", 1

        await self._save_holding(symbol, trigger_type, candidate, scenario, execution=execution)
        if execution and execution.get("success"):
            logger.info(
                "ROTATION_ENTRY+TRADE %s (%s) score=%s/%s qty=%.8f @ %.6f",
                symbol,
                trigger_type,
                buy_score,
                min_score,
                _safe_float(execution.get("quantity"), 0.0),
                _safe_float(execution.get("executed_price"), 0.0),
            )
        else:
            logger.info("ROTATION_ENTRY %s (%s) score=%s/%s", symbol, trigger_type, buy_score, min_score)
        return True, "rotated", 1

    async def process_candidates_file(self, candidates_json_path: str) -> Tuple[int, int, int]:
        """Process Phase1 output json and store decisions.

        Returns:
            (entry_count, no_entry_count, sold_count)
        """
        self._reset_cycle_exit_counts()
        sold_count = await self.update_holdings()
        with open(candidates_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        entry_count = 0
        no_entry_count = 0
        rotations_done = 0

        for trigger_type, items in data.items():
            if trigger_type == "metadata":
                continue
            if not isinstance(items, list):
                continue

            trigger_holdings_skipped = 0
            for item in items:
                symbol = item.get("symbol")
                if not symbol:
                    continue
                if not item.get("theme"):
                    item["theme"] = classify_symbol_theme(symbol)

                if is_crypto_symbol_in_holdings(self.cursor, symbol):
                    logger.info("Skip already-held symbol: %s", symbol)
                    trigger_holdings_skipped += 1
                    continue

                cooldown_active, cooldown_reason = self._is_reentry_cooldown_active(symbol)
                if cooldown_active:
                    await self._save_watchlist(symbol, trigger_type, item, default_scenario(), cooldown_reason)
                    no_entry_count += 1
                    logger.info("NO_ENTRY %s (%s): %s", symbol, trigger_type, cooldown_reason)
                    continue

                scenario = await self.analyze_candidate(symbol, trigger_type, item)
                buy_score = int(_safe_float(scenario.get("buy_score"), 0))
                min_score = int(_safe_float(scenario.get("min_score"), 6))
                decision = str(scenario.get("decision", "no_entry")).lower()

                if decision == "entry" and buy_score >= min_score:
                    if get_crypto_holdings_count(self.cursor) >= self.max_slots:
                        if rotations_done < self.ROTATION_MAX_PER_CYCLE:
                            rotated, reason, rotated_sold_count = await self._try_rotation_entry(
                                symbol=symbol,
                                trigger_type=trigger_type,
                                candidate=item,
                                scenario=scenario,
                                buy_score=buy_score,
                                min_score=min_score,
                            )
                            sold_count += rotated_sold_count
                            if rotated:
                                entry_count += 1
                                rotations_done += 1
                                continue
                            await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                            no_entry_count += 1
                            logger.info("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)
                            continue

                        reason = (
                            f"max slots reached ({self.max_slots}), "
                            f"rotation limit reached ({self.ROTATION_MAX_PER_CYCLE}/cycle)"
                        )
                        await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                        no_entry_count += 1
                        logger.info("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)
                        continue

                    execution = None
                    if self.execute_trades:
                        if self.trade_mode != "paper":
                            reason = f"unsupported trade_mode={self.trade_mode}"
                            await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                            no_entry_count += 1
                            logger.warning("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)
                            continue

                        if not self.paper_trader:
                            reason = "paper trader not initialized"
                            await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                            no_entry_count += 1
                            logger.warning("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)
                            continue

                        execution = self.paper_trader.buy(
                            symbol=symbol,
                            quote_amount=self.quote_amount,
                            limit_price=None,
                            metadata={"trigger_type": trigger_type},
                        )
                        if not execution.get("success"):
                            reason = f"paper buy failed: {execution.get('message', 'unknown')}"
                            await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                            no_entry_count += 1
                            logger.warning("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)
                            continue

                    await self._save_holding(symbol, trigger_type, item, scenario, execution=execution)
                    entry_count += 1
                    if execution and execution.get("success"):
                        logger.info(
                            "ENTRY+TRADE %s (%s) score=%s/%s qty=%.8f @ %.6f",
                            symbol,
                            trigger_type,
                            buy_score,
                            min_score,
                            _safe_float(execution.get("quantity"), 0.0),
                            _safe_float(execution.get("executed_price"), 0.0),
                        )
                    else:
                        logger.info("ENTRY %s (%s) score=%s/%s", symbol, trigger_type, buy_score, min_score)
                else:
                    reason = (
                        f"decision={decision}, score={buy_score}/{min_score}"
                        if decision != "entry" or buy_score < min_score
                        else "no entry"
                    )
                    await self._save_watchlist(symbol, trigger_type, item, scenario, reason)
                    no_entry_count += 1
                    logger.info("NO_ENTRY %s (%s): %s", symbol, trigger_type, reason)

            if trigger_holdings_skipped and trigger_holdings_skipped == len(items):
                logger.info(
                    "All candidates skipped for %s: already in holdings (%d/%d)",
                    trigger_type,
                    trigger_holdings_skipped,
                    len(items),
                )

        logger.info(
            "Cycle exit summary - stop_loss=%d, rotation=%d, normal=%d, total=%d",
            self._cycle_exit_counts.get("stop_loss", 0),
            self._cycle_exit_counts.get("rotation", 0),
            self._cycle_exit_counts.get("normal", 0),
            sold_count,
        )

        return entry_count, no_entry_count, sold_count


async def _amain(candidates_json_path: str, db_path: str, language: str, rotation_reentry_cooldown_hours: float = 0.0):
    agent = CryptoTrackingAgent(
        db_path=db_path,
        language=language,
        rotation_reentry_cooldown_hours=rotation_reentry_cooldown_hours,
    )
    await agent.initialize()
    try:
        entry_count, no_entry_count, sold_count = await agent.process_candidates_file(candidates_json_path)
        logger.info(
            "Crypto process complete - entry=%d, no_entry=%d, sold=%d",
            entry_count,
            no_entry_count,
            sold_count,
        )
    finally:
        await agent.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Process crypto candidates and store decisions.")
    parser.add_argument("candidates_json", help="Path to phase1 candidate json file")
    parser.add_argument("--db-path", default="stock_tracking_db.sqlite", help="SQLite DB path")
    parser.add_argument("--language", default="ko", help="ko or en")
    parser.add_argument("--timeframe", default="1h", help="Signal timeframe label (e.g. 1h,2h,4h)")
    parser.add_argument("--execute-trades", action="store_true", help="Execute paper trades on entry")
    parser.add_argument("--trade-mode", default="paper", help="paper or real (real not implemented)")
    parser.add_argument("--quote-amount", type=float, default=100.0, help="Quote amount per buy order in USD")
    parser.add_argument(
        "--rotation-reentry-cooldown-hours",
        type=float,
        default=0.0,
        help="Optional cooldown window to block re-entry into recently sold symbols (0 disables)",
    )
    args = parser.parse_args()

    async def _run():
        agent = CryptoTrackingAgent(
            db_path=args.db_path,
            language=args.language,
            timeframe=args.timeframe,
            execute_trades=args.execute_trades,
            trade_mode=args.trade_mode,
            quote_amount=args.quote_amount,
            rotation_reentry_cooldown_hours=max(args.rotation_reentry_cooldown_hours, 0.0),
        )
        await agent.initialize()
        try:
            entry_count, no_entry_count, sold_count = await agent.process_candidates_file(args.candidates_json)
            logger.info(
                "Crypto phase3 process complete - entry=%d, no_entry=%d, sold=%d, execute_trades=%s",
                entry_count,
                no_entry_count,
                sold_count,
                args.execute_trades,
            )
        finally:
            await agent.close()

    asyncio.run(_run())
