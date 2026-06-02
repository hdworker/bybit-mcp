"""Private account data tools (read-only, no mandate gate, requires API key).

These tools call PRIVATE endpoints (signed) — they need a configured
``BYBIT_API_KEY`` / ``BYBIT_API_SECRET``. They never modify broker state and
are NOT gated by the mandate (the mandate governs WRITE actions only). If
no credentials are configured, the client returns a 10003 / 10004 error from
Bybit which we surface as a normal error envelope.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from bybit_mcp.client.rest import BybitAPIError, BybitError, BybitTransportError
from bybit_mcp.server.state import get_client

logger = logging.getLogger(__name__)


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(exc: Exception, op: str) -> str:
    if isinstance(exc, BybitAPIError):
        return json.dumps(
            {"status": "error", "op": op, "retCode": exc.ret_code, "retMsg": exc.ret_msg},
            ensure_ascii=False,
        )
    if isinstance(exc, BybitTransportError):
        return json.dumps(
            {"status": "error", "op": op, "error": str(exc)}, ensure_ascii=False
        )
    return json.dumps({"status": "error", "op": op, "error": str(exc)}, ensure_ascii=False)


def register_account_tools(mcp: FastMCP) -> None:
    """Register all account read tools on the given FastMCP server."""

    @mcp.tool(
        name="bybit_get_wallet_balance",
        description=(
            "Bybit v5 wallet balance (signed). Default accountType=UNIFIED. "
            "Returns the unified account snapshot with per-coin equity, "
            "walletBalance, availableToWithdraw, unrealisedPnl."
        ),
    )
    async def bybit_get_wallet_balance(
        account_type: str = "UNIFIED",
        coins: str | None = None,
    ) -> str:
        """Fetch account wallet balance.

        Args:
            account_type: ``UNIFIED`` | ``CONTRACT`` | ``SPOT``.
            coins: Optional comma-separated coin list, e.g. ``"BTC,USDT"``.
                Omit for all coins in the account.
        """
        coin_list = [c.strip() for c in coins.split(",")] if coins else None
        try:
            async with get_client() as client:
                rows = await client.get_wallet_balance(
                    account_type=account_type, coins=coin_list,
                )
            return _ok({"accountType": account_type, "balances": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_wallet_balance")

    @mcp.tool(
        name="bybit_get_positions",
        description=(
            "Bybit v5 open positions (signed). Returns list of "
            "{symbol, side, size, avgPrice, markPrice, liqPrice, leverage, "
            "positionValue, unrealisedPnl, positionIdx, takeProfit, stopLoss}."
        ),
    )
    async def bybit_get_positions(
        category: str = "linear",
        symbol: str | None = None,
        settle_coin: str | None = None,
        limit: int = 200,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_positions(
                    category=category, symbol=symbol,
                    settle_coin=settle_coin, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "positions": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_positions")

    @mcp.tool(
        name="bybit_get_open_orders",
        description=(
            "Bybit v5 open (resting) orders (signed). Returns list of "
            "{orderId, orderLinkId, symbol, side, orderType, price, qty, "
            "avgPrice, cumExecQty, orderStatus}."
        ),
    )
    async def bybit_get_open_orders(
        category: str = "linear",
        symbol: str | None = None,
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_open_orders(
                    category=category, symbol=symbol, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "orders": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_open_orders")

    @mcp.tool(
        name="bybit_get_order_history",
        description=(
            "Bybit v5 historical orders (signed, up to 2 years). Returns list "
            "of order records (same fields as open orders plus createdTime, "
            "updatedTime, cumExecFee, cumExecValue)."
        ),
    )
    async def bybit_get_order_history(
        category: str = "linear",
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_order_history(
                    category=category, symbol=symbol,
                    start_ms=start_ms, end_ms=end_ms, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "orders": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_order_history")
