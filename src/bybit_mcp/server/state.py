"""Server-wide Bybit client + gate state.

A single :class:`BybitClient` is opened at MCP server start (async lifespan)
and shared across all tool invocations. The :class:`MandateGate` is created
per-tool-invocation (cheap, reads from disk).

The ``broker`` key is configurable via ``BYBIT_BROKER_KEY`` (default ``"bybit"``)
so the per-broker mandate/halt/counter paths in the runtime root are
broker-isolated. A user with multiple live channels (``bybit`` / ``okx`` /
``binance`` …) can point each MCP server at its own broker key.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from bybit_mcp.client.rest import BybitClient, BybitConfig
from bybit_mcp.safety.guard import MandateGate

logger = logging.getLogger(__name__)


def broker_key() -> str:
    """Return the broker key for mandate/halt/counter lookups (default ``"bybit"``)."""
    return os.getenv("BYBIT_BROKER_KEY", "bybit").strip().lower() or "bybit"


def get_client() -> BybitClient:
    """Return a *new* :class:`BybitClient` from the current env config.

    Use as ``async with get_client() as client:``. Created fresh per call so
    the MCP server's lifespan (which closes one shared client) is not coupled
    to tool implementations.
    """
    return BybitClient(BybitConfig.from_env())


def make_gate(session_id: str = "") -> MandateGate:
    """Return a fresh :class:`MandateGate` bound to the configured broker key."""
    return MandateGate(broker=broker_key(), session_id=session_id)


@asynccontextmanager
async def server_lifespan() -> AsyncIterator[dict]:
    """Async lifespan context: warm a shared BybitClient for the server lifetime.

    Use with ``FastMCP(lifespan=server_lifespan)`` to keep one client open
    across tool calls (TCP connection reuse, time-sync freshness).
    """
    client = BybitClient(BybitConfig.from_env())
    await client.__aenter__()
    try:
        yield {"client": client, "broker": broker_key()}
    finally:
        await client.__aexit__(None, None, None)
