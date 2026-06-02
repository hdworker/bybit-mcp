"""FastMCP server entry point for bybit-mcp.

Run with::

    # stdio transport (default — for embedding into Vibe-Trading's MCP registry)
    python -m bybit_mcp.server.mcp_server

    # HTTP transport (for development / curl testing)
    python -m bybit_mcp.server.mcp_server --transport http --port 8001
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from fastmcp import FastMCP

from bybit_mcp import __version__
from bybit_mcp.server.state import broker_key
from bybit_mcp.server.tools_account import register_account_tools
from bybit_mcp.server.tools_market import register_market_tools
from bybit_mcp.server.tools_order import register_order_tools

logger = logging.getLogger("bybit_mcp")


def build_server() -> FastMCP:
    """Construct the FastMCP server with all 17 tools registered."""
    mcp = FastMCP(
        name="bybit-mcp",
        version=__version__,
        instructions=(
            "Bybit v5 broker MCP server. Read tools (tickers / kline / orderbook / "
            "funding / OI / instruments / wallet / positions / orders) require "
            "API credentials for private endpoints. Write tools "
            "(place_order / amend_order / cancel_order / cancel_all_orders / "
            "set_leverage / set_trading_stop) are GATED by a user-side mandate "
            "at <runtime_root>/live/<broker>/mandate.json — orders are DENIED "
            "when the mandate is missing, expired, the kill switch is tripped, "
            "the symbol is excluded, the instrument / asset class is not "
            "permitted, or the notional / exposure / leverage / daily-count / "
            "funding caps are breached. Every decision (ALLOW / DENY / PAUSE) "
            "writes one redacted record to <runtime_root>/live/audit.jsonl."
        ),
    )
    register_market_tools(mcp)
    register_account_tools(mcp)
    register_order_tools(mcp)
    return mcp


def _setup_logging() -> None:
    level = os.getenv("BYBIT_MCP_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bybit-mcp",
        description="Bybit v5 MCP server for Vibe-Trading.",
    )
    parser.add_argument(
        "--transport", choices=["stdio", "http", "sse", "streamable-http"],
        default="stdio", help="MCP transport (default: stdio).",
    )
    parser.add_argument(
        "--host", default=os.getenv("BYBIT_MCP_HOST", "127.0.0.1"),
        help="HTTP host (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("BYBIT_MCP_PORT", "8001")),
        help="HTTP port (default: 8001).",
    )
    parser.add_argument(
        "--broker-key", default=os.getenv("BYBIT_BROKER_KEY", "bybit"),
        help="Broker key for mandate / halt / counter lookups (default: bybit).",
    )
    parser.add_argument(
        "--show-banner", action="store_true",
        default=os.getenv("BYBIT_MCP_SHOW_BANNER", "false").lower() in {"1", "true"},
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Process entry point for the ``bybit-mcp`` console script."""
    _setup_logging()
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    # Export broker key into env so server.state picks it up consistently.
    os.environ["BYBIT_BROKER_KEY"] = args.broker_key
    logger.info(
        "bybit-mcp v%s starting (transport=%s broker=%s host=%s port=%d)",
        __version__, args.transport, broker_key(), args.host, args.port,
    )

    mcp = build_server()
    if args.transport == "stdio":
        mcp.run(transport="stdio", show_banner=args.show_banner)
        return

    transport = "http" if args.transport == "streamable-http" else args.transport
    mcp.run(
        transport=transport,  # type: ignore[arg-type]
        show_banner=args.show_banner,
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
