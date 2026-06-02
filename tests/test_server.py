"""Tests for the FastMCP server: tool registration count, schemas present."""

from __future__ import annotations

import pytest

from bybit_mcp.server.mcp_server import build_server


@pytest.mark.asyncio
async def test_all_tools_registered():
    """The full tool surface must be present (17 tools: 11 read + 6 write)."""
    mcp = build_server()
    tools = await mcp.list_tools()
    names = sorted(t.name for t in tools)
    assert names == sorted([
        "bybit_amend_order",
        "bybit_cancel_all_orders",
        "bybit_cancel_order",
        "bybit_get_funding_history",
        "bybit_get_instruments_info",
        "bybit_get_kline",
        "bybit_get_open_interest",
        "bybit_get_open_orders",
        "bybit_get_order_history",
        "bybit_get_orderbook",
        "bybit_get_positions",
        "bybit_get_recent_trades",
        "bybit_get_tickers",
        "bybit_get_wallet_balance",
        "bybit_place_order",
        "bybit_set_leverage",
        "bybit_set_trading_stop",
    ])


@pytest.mark.asyncio
async def test_tool_schemas_have_descriptions():
    mcp = build_server()
    tools = await mcp.list_tools()
    for tool in tools:
        assert tool.description, f"tool {tool.name} has no description"
        # Parameters should be present and a dict (or empty dict for no-arg)
        assert tool.parameters is None or isinstance(tool.parameters, dict)
