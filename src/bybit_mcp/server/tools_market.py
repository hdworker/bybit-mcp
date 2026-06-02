"""Read-only market data tools (no mandate gate).

Each tool returns a JSON string (FastMCP convention) so the LLM can consume
the payload directly. Errors are returned as ``{"status": "error", ...}``
envelopes (fail-soft at the read path; the gate is what fail-closes for writes).
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


def register_market_tools(mcp: FastMCP) -> None:
    """Register all market read tools on the given FastMCP server."""

    @mcp.tool(
        name="bybit_get_tickers",
        description=(
            "Get Bybit v5 tickers for a product category. "
            "Public, no auth required. Returns: list of {symbol, lastPrice, "
            "indexPrice, markPrice, price24hPcnt, volume24h, turnover24h, "
            "openInterest, fundingRate, nextFundingTime, bid1Price, ask1Price}."
        ),
    )
    async def bybit_get_tickers(
        category: str = "linear",
        symbol: str | None = None,
    ) -> str:
        """Fetch Bybit v5 tickers.

        Args:
            category: ``spot`` | ``linear`` | ``inverse`` | ``option``.
            symbol: Optional symbol filter (e.g. ``BTCUSDT``). Omit for all
                tickers in the category.
        """
        try:
            async with get_client() as client:
                rows = await client.get_tickers(category=category, symbol=symbol)
            return _ok({"category": category, "symbol": symbol, "tickers": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_tickers")

    @mcp.tool(
        name="bybit_get_kline",
        description=(
            "Fetch Bybit v5 klines (candles). Each row is "
            "[start_ms, open, high, low, close, volume, turnover]. Public, no auth."
        ),
    )
    async def bybit_get_kline(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        interval: str = "5",
        limit: int = 200,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> str:
        """Fetch klines.

        Args:
            category: ``spot`` | ``linear`` | ``inverse``.
            symbol: e.g. ``BTCUSDT``.
            interval: ``1`` / ``3`` / ``5`` / ``15`` / ``30`` / ``60`` / ``120``
                / ``240`` / ``360`` / ``720`` / ``D`` / ``W`` / ``M``.
            limit: 1..1000 (default 200, server caps at 1000).
            start_ms: Optional start time in milliseconds since epoch.
            end_ms: Optional end time in milliseconds since epoch.
        """
        try:
            async with get_client() as client:
                rows = await client.get_kline(
                    category=category, symbol=symbol, interval=interval,
                    limit=limit, start_ms=start_ms, end_ms=end_ms,
                )
            return _ok({"category": category, "symbol": symbol, "interval": interval,
                        "klines": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_kline")

    @mcp.tool(
        name="bybit_get_orderbook",
        description=(
            "Bybit v5 L2 order book snapshot for a symbol. Returns "
            "{bids: [[price, size], ...], asks: [[price, size], ...], ts, u}."
        ),
    )
    async def bybit_get_orderbook(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                ob = await client.get_orderbook(category=category, symbol=symbol, limit=limit)
            return _ok({"category": category, "symbol": symbol, **ob})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_orderbook")

    @mcp.tool(
        name="bybit_get_funding_history",
        description=(
            "Bybit v5 historical funding rate for a perpetual. Returns list of "
            "{symbol, fundingRate, fundingRateTimestamp}."
        ),
    )
    async def bybit_get_funding_history(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_funding_history(
                    category=category, symbol=symbol,
                    start_ms=start_ms, end_ms=end_ms, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "funding": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_funding_history")

    @mcp.tool(
        name="bybit_get_open_interest",
        description=(
            "Bybit v5 open interest for a perpetual. Returns list of "
            "{symbol, openInterest, timestamp}."
        ),
    )
    async def bybit_get_open_interest(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        interval_time: str = "5min",
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_open_interest(
                    category=category, symbol=symbol,
                    interval_time=interval_time, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "oi": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_open_interest")

    @mcp.tool(
        name="bybit_get_instruments_info",
        description=(
            "Bybit v5 instrument metadata (lot size filter, price filter, "
            "leverage limits, etc.) for a category, optionally filtered by symbol."
        ),
    )
    async def bybit_get_instruments_info(
        category: str = "linear",
        symbol: str | None = None,
        limit: int = 200,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_instruments_info(
                    category=category, symbol=symbol, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "instruments": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_instruments_info")

    @mcp.tool(
        name="bybit_get_recent_trades",
        description=(
            "Bybit v5 recent public trades for a symbol. Returns list of "
            "[execId, price, size, side, time]."
        ),
    )
    async def bybit_get_recent_trades(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        limit: int = 60,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_public_trade_history(
                    category=category, symbol=symbol, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "trades": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_recent_trades")
