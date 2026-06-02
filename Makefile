.PHONY: install dev test lint format run run-stdio run-sse clean

PY ?= python3

install:
	$(PY) -m pip install -e ".[dev,vibe]"

dev:
	$(PY) -m pip install -e ".[dev,vibe]"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests

format:
	$(PY) -m ruff format src tests

# Default MCP transport — stdio (works with Vibe-Trading, Claude Desktop, Cursor, OpenClaw).
run:
	$(PY) -m bybit_mcp.server.mcp_server

# Explicit stdio (default)
run-stdio:
	$(PY) -m bybit_mcp.server.mcp_server --transport stdio

# SSE transport for web MCP clients
run-sse:
	$(PY) -m bybit_mcp.server.mcp_server --transport sse --host 127.0.0.1 --port 8765

clean:
	rm -rf build dist src/*.egg-info .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
