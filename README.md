# bybit-mcp

[![CI](https://github.com/hdworker/bybit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/hdworker/bybit-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Bybit v5 broker MCP server for [Vibe-Trading](https://github.com/your-org/vibe-trading).

Exposes 17 tools to an MCP-aware agent (LLM):

- **11 read** (market data + private account snapshots) — no mandate gate.
- **6 write** (place / amend / cancel / cancel-all / set leverage / set TP/SL) — **gated by the user-side mandate**, fail-closed.

The mandate file, kill switch, daily counter, and audit ledger live in the same
filesystem layout Vibe-Trading's in-repo `LiveOrderGuardTool` reads from, so the
in-process guard and the bybit-mcp guard see **the same state** and the audit
ledger is unified.

## Quick start

```bash
# 1. Install
cd ~/eth/bybit-mcp
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
$EDITOR .env                  # set BYBIT_API_KEY / BYBIT_API_SECRET

# 3. Commit a mandate
mkdir -p ~/.vibe-trading/live/bybit
$EDITOR ~/.vibe-trading/live/bybit/mandate.json    # see schema below

# 4. Run (stdio for embedding into Vibe-Trading)
python -m bybit_mcp.server.mcp_server --transport stdio

# 4b. Or run over HTTP for curl testing
python -m bybit_mcp.server.mcp_server --transport http --port 8001
```

## Tool surface

| Tool | Type | Gated | Notes |
|------|------|------|-------|
| `bybit_get_tickers` | read | no | public, no auth |
| `bybit_get_kline` | read | no | public, no auth |
| `bybit_get_orderbook` | read | no | public, no auth |
| `bybit_get_funding_history` | read | no | public, no auth |
| `bybit_get_open_interest` | read | no | public, no auth |
| `bybit_get_instruments_info` | read | no | public, no auth |
| `bybit_get_recent_trades` | read | no | public, no auth |
| `bybit_get_wallet_balance` | read | no | signed, needs API creds |
| `bybit_get_positions` | read | no | signed, needs API creds |
| `bybit_get_open_orders` | read | no | signed, needs API creds |
| `bybit_get_order_history` | read | no | signed, needs API creds |
| `bybit_place_order` | write | **yes** | deny on missing mandate / kill switch / cap breach |
| `bybit_amend_order` | write | **yes** | enforces the LARGER of (explicit notional, new_qty × live price) |
| `bybit_cancel_order` | write | **yes** | single order |
| `bybit_cancel_all_orders` | write | **yes** | bulk |
| `bybit_set_leverage` | write | **yes** | structural check only |
| `bybit_set_trading_stop` | write | **yes** | TP/SL price change does not alter notional math |

## Mandate file

A valid `mandate.json` is required at `<runtime_root>/live/bybit/mandate.json`
before any write tool is callable. Without it, every order attempt returns
`status="blocked", decision="deny", reason="no valid mandate on file"`.

The schema matches Vibe-Trading's `src.live.mandate.model.Mandate` EXACTLY so
a mandate committed by the Vibe-Trading consent UX is readable by bybit-mcp
without translation, and vice versa.

```json
{
  "schema_version": 1,
  "hard_caps": {
    "account_funding_usd": 5000.0,
    "max_order_notional_usd": 1000.0,
    "max_total_exposure_usd": 5000.0,
    "max_leverage": 3.0,
    "allowed_instruments": ["crypto"],
    "max_trades_per_day": 50
  },
  "universe": {
    "asset_classes": ["crypto"],
    "min_market_cap_usd": null,
    "min_avg_daily_volume_usd": null,
    "exclude_symbols": ["DOGEUSDT"]
  },
  "consent": {
    "created_at": "2026-06-01T00:00:00+00:00",
    "consent_token_sha256": "<sha256 of the user-side consent artifact>",
    "broker": "bybit",
    "account_ref": "bybit-acct-0001",
    "expires_at": "2026-07-01T00:00:00+00:00"
  },
  "flatten_on_halt": false
}
```

## 6-step fail-closed gate

Every write tool runs the same gate (mirrors Vibe-Trading's
`src.live.order_guard.LiveOrderGuardTool`):

1. `load_mandate` — no mandate / wrong `schema_version` → DENY.
2. `expires_at` — past the user-set expiry → PAUSE_FOR_REAUTH.
3. `halt_flag_set` — kill switch tripped → DENY, no remote call.
4. `extract_order_intent` — unparseable args → DENY.
5. `quantity → notional` — quantity-only orders derive notional from a live
   quote; no quote → DENY (fail-closed). H3: if both `quantity` and
   `notional_usd` are present, the LARGER is enforced.
6. `check_mandate` — exclude-list, instrument allowance, asset class, single
   notional cap, post-trade exposure cap, leverage cap, daily count, funding
   ceiling. Structural breaches → DENY; quantitative breaches → PAUSE_FOR_REAUTH.

The daily counter is incremented **only** on a confirmed ALLOW whose forwarded
broker result is non-error (a failed forward never placed an order and never
consumes a count, H2).

Every decision writes one redacted record to `<runtime_root>/live/audit.jsonl`.

## Audit ledger

`<runtime_root>/live/audit.jsonl` is the unified live-action ledger. bybit-mcp
writes here, Vibe-Trading's native guard writes here, and the CLI / SSE relay
reads from here.

Each record (redacted via the `redact_payload` helper, so `api_key`,
`secret`, `*token*`, `account_number`, `routing_number`, `ssn`, etc. are
`"[redacted]"`):

```json
{
  "audit_id": "la_3f2c…",
  "ts": "2026-06-02T09:15:49.482+00:00",
  "session_id": "vibe-2026-06-02-session-001",
  "kind": "order_placed",
  "outcome": "accepted",
  "server": "bybit",
  "remote_tool": "bybit_place_order",
  "intent_normalized": "buy $100 BTCUSDT (linear)",
  "mandate_snapshot_ref": "<sha256 of the mandate's consent token>",
  "consent_record_ref": "bybit-acct-0001",
  "broker_request": { "category": "linear", "symbol": "BTCUSDT", "side": "Buy", "qty": "0.001" },
  "broker_response": { "orderId": "1234567890", "orderLinkId": "" },
  "gate_decision": { "allowed": true, "decision": "allow", "checked_limits": [...] },
  "error": null
}
```

## Kill switch

Stop all live activity instantly, independent of the LLM cooperating:

```bash
# Trip the GLOBAL switch (halts all brokers)
touch ~/.vibe-trading/live/HALT
# write the trip attribution
python -c "from bybit_mcp.safety.halt import trip_halt; trip_halt('cli', 'manual stop')"

# Trip a per-broker switch (halts bybit only)
python -c "from bybit_mcp.safety.halt import trip_halt; trip_halt('cli', 'manual stop', broker='bybit')"

# Clear (this is a privileged surface action, NOT exposed as an MCP tool)
python -c "from bybit_mcp.safety.halt import clear_halt; clear_halt()"
python -c "from bybit_mcp.safety.halt import clear_halt; clear_halt(broker='bybit')"
```

A user can also `touch` the sentinel directly (the `by` / `reason` JSON body
is attribution only; the file's *existence* is what enforces the halt).

## Integration with Vibe-Trading

Add an entry to your Vibe-Trading `agent.json` MCP registry:

```json
{
  "mcpServers": {
    "bybit": {
      "command": "python",
      "args": ["-m", "bybit_mcp.server.mcp_server", "--transport", "stdio"],
      "env": {
        "VIBE_RUNTIME_ROOT": "~/.vibe-trading",
        "BYBIT_API_KEY": "${BYBIT_API_KEY}",
        "BYBIT_API_SECRET": "${BYBIT_API_SECRET}",
        "BYBIT_TESTNET": "false",
        "BYBIT_BROKER_KEY": "bybit"
      }
    }
  }
}
```

Vibe-Trading's native `LiveOrderGuardTool` (in-repo, wrapping the
`MCPRemoteTool` instances) and the bybit-mcp server share:

- The **mandate file** at `<runtime_root>/live/<broker>/mandate.json`.
- The **halt sentinel** at `<runtime_root>/live/HALT` (and per-broker).
- The **daily counter** at `<runtime_root>/live/<broker>/trade_counter.json`.
- The **audit ledger** at `<runtime_root>/live/audit.jsonl`.

This means a single mandate commit and a single `HALT` sentinel covers both
the in-process and the cross-process (MCP) order paths.

## Environment

| Var | Default | Purpose |
|-----|---------|---------|
| `BYBIT_API_KEY` | (empty = public-only) | Bybit API key |
| `BYBIT_API_SECRET` | (empty) | Bybit API secret |
| `BYBIT_TESTNET` | `false` | Use testnet base URL |
| `BYBIT_HTTP_TIMEOUT` | `10` | httpx request timeout (seconds) |
| `BYBIT_RECV_WINDOW` | `5000` | recv_window for signed requests (ms) |
| `BYBIT_BROKER_KEY` | `bybit` | Per-broker mandate/halt/counter path key |
| `VIBE_RUNTIME_ROOT` | `~/.vibe-trading` | Runtime root for mandate/audit/halt/counter |
| `BYBIT_MCP_LOG_LEVEL` | `INFO` | Logger level |
| `BYBIT_MCP_HOST` | `127.0.0.1` | HTTP host (when `--transport http`) |
| `BYBIT_MCP_PORT` | `8001` | HTTP port (when `--transport http`) |

## Architecture

```
+------------------------+        +-------------------------+
|   Vibe-Trading agent   | stdio  |   bybit-mcp process     |
|   - agent loop         |<------>|   - FastMCP server      |
|   - native guard (in-  |  HTTP  |   - MandateGate         |
|     process MCP tools) |        |   - 17 tools (11R+6W)   |
+-----------+------------+        +------------+------------+
            |                                  |
            |   <runtime_root>/live/...        |
            +----------------------------------+
                  shared state, audit ledger
```

The MCP server is **stateless across tool calls** — the mandate / halt / counter
are re-read from disk on every invocation, so a user-side commit / trip is
immediately visible to the next order attempt. The shared `BybitClient` keeps
a single TCP connection open + a synced clock across the server lifetime (see
`server_lifespan` in `mcp_server.py`).

## Development

```bash
make install       # pip install -e ".[dev]"
make test          # pytest (95 tests, ~2s)
make lint          # ruff check
make format        # black + ruff --fix
make run-stdio     # stdio transport
make run-sse       # HTTP transport on :8001
```

## License

MIT
