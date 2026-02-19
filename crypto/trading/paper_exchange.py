"""Paper trading adapter for crypto Phase 3."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

import yfinance as yf

logger = logging.getLogger(__name__)


class PaperCryptoTrading:
    """Simple paper execution layer.

    Notes:
    - No order book simulation yet.
    - Fills at current market price with configurable slippage.
    - Records executions to `crypto_order_executions`.
    """

    def __init__(
        self,
        cursor,
        conn,
        fee_rate: float = 0.001,
        slippage_rate: float = 0.0005,
    ):
        self.cursor = cursor
        self.conn = conn
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate

    def get_current_price(self, symbol: str) -> float:
        query_plan = [("1d", "1m"), ("5d", "1h"), ("30d", "1d")]
        ticker = yf.Ticker(symbol)
        last_error = None

        for period, interval in query_plan:
            for attempt in range(3):
                try:
                    hist = ticker.history(period=period, interval=interval, auto_adjust=False)
                    if hist is not None and not hist.empty:
                        return float(hist["Close"].iloc[-1])
                except Exception as e:
                    last_error = e
                time.sleep(0.3 * (attempt + 1))

        # Optional fallback to fast_info when history endpoint is unstable.
        try:
            fi = getattr(ticker, "fast_info", None) or {}
            last_price = fi.get("lastPrice")
            if last_price:
                return float(last_price)
        except Exception:
            pass

        if last_error:
            logger.warning("Paper price fetch failed for %s after retries: %s", symbol, last_error)
        return 0.0

    def _record_execution(
        self,
        symbol: str,
        side: str,
        order_type: str,
        status: str,
        requested_price: Optional[float],
        executed_price: float,
        quantity: float,
        quote_amount: float,
        fee: float,
        mode: str = "paper",
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute(
            """
            INSERT INTO crypto_order_executions
            (symbol, side, order_type, status, requested_price, executed_price, quantity,
             quote_amount, fee_amount, mode, message, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                side,
                order_type,
                status,
                requested_price,
                executed_price,
                quantity,
                quote_amount,
                fee,
                mode,
                message,
                None if metadata is None else str(metadata),
                now,
            ),
        )
        self.conn.commit()
        return int(self.cursor.lastrowid)

    def buy(
        self,
        symbol: str,
        quote_amount: float,
        limit_price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        market_price = self.get_current_price(symbol)
        if market_price <= 0:
            order_id = self._record_execution(
                symbol=symbol,
                side="buy",
                order_type="market" if not limit_price else "limit",
                status="rejected",
                requested_price=limit_price,
                executed_price=0.0,
                quantity=0.0,
                quote_amount=quote_amount,
                fee=0.0,
                message="Price unavailable",
                metadata=metadata,
            )
            return {"success": False, "order_id": order_id, "message": "Price unavailable"}

        exec_price = market_price * (1.0 + self.slippage_rate)
        if limit_price and exec_price > limit_price:
            order_id = self._record_execution(
                symbol=symbol,
                side="buy",
                order_type="limit",
                status="unfilled",
                requested_price=limit_price,
                executed_price=0.0,
                quantity=0.0,
                quote_amount=quote_amount,
                fee=0.0,
                message="Limit not reached",
                metadata=metadata,
            )
            return {"success": False, "order_id": order_id, "message": "Limit not reached"}

        qty = quote_amount / exec_price if exec_price > 0 else 0.0
        fee = quote_amount * self.fee_rate

        order_id = self._record_execution(
            symbol=symbol,
            side="buy",
            order_type="market" if not limit_price else "limit",
            status="filled",
            requested_price=limit_price,
            executed_price=exec_price,
            quantity=qty,
            quote_amount=quote_amount,
            fee=fee,
            message="Filled",
            metadata=metadata,
        )
        return {
            "success": True,
            "order_id": order_id,
            "symbol": symbol,
            "executed_price": exec_price,
            "quantity": qty,
            "quote_amount": quote_amount,
            "fee": fee,
        }

    def sell_all(
        self,
        symbol: str,
        quantity: float,
        limit_price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        market_price = self.get_current_price(symbol)
        if market_price <= 0 or quantity <= 0:
            order_id = self._record_execution(
                symbol=symbol,
                side="sell",
                order_type="market" if not limit_price else "limit",
                status="rejected",
                requested_price=limit_price,
                executed_price=0.0,
                quantity=quantity,
                quote_amount=0.0,
                fee=0.0,
                message="Invalid price or quantity",
                metadata=metadata,
            )
            return {"success": False, "order_id": order_id, "message": "Invalid price or quantity"}

        exec_price = market_price * (1.0 - self.slippage_rate)
        if limit_price and exec_price < limit_price:
            order_id = self._record_execution(
                symbol=symbol,
                side="sell",
                order_type="limit",
                status="unfilled",
                requested_price=limit_price,
                executed_price=0.0,
                quantity=quantity,
                quote_amount=0.0,
                fee=0.0,
                message="Limit not reached",
                metadata=metadata,
            )
            return {"success": False, "order_id": order_id, "message": "Limit not reached"}

        gross = quantity * exec_price
        fee = gross * self.fee_rate
        net = gross - fee

        order_id = self._record_execution(
            symbol=symbol,
            side="sell",
            order_type="market" if not limit_price else "limit",
            status="filled",
            requested_price=limit_price,
            executed_price=exec_price,
            quantity=quantity,
            quote_amount=gross,
            fee=fee,
            message="Filled",
            metadata=metadata,
        )
        return {
            "success": True,
            "order_id": order_id,
            "symbol": symbol,
            "executed_price": exec_price,
            "quantity": quantity,
            "gross_amount": gross,
            "fee": fee,
            "net_amount": net,
        }
