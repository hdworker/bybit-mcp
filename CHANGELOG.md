# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-06-02

### Added
- 17 MCP tools: 11 read (market data + account snapshots) + 6 gated write (place/amend/cancel/set-leverage/set-TP-SL).
- 6-step fail-closed `MandateGate` — mirrors Vibe-Trading's `LiveOrderGuardTool` semantics.
- Per-broker mandate, halt sentinel, daily counter, and audit ledger paths.
- HMAC-SHA256 signing for Bybit v5 authenticated endpoints with `TimeSync` clock drift compensation.
- Redaction layer (credentials, PII, account numbers) with `account_ref` preservation.
- 7 public market tools: tickers, klines, orderbook, funding history, open interest, instruments info, recent trades.
- 4 signed account tools: wallet balance, positions, open orders, order history.
- 6 gated order tools: place order, amend order, cancel order, cancel all orders, set leverage, set trading stop.
- `OrderIntent` extractors for place/amend order normalisation.
- `BreachEvent` with `kind ∈ {universe, instrument, quantitative}` → DENY / PAUSE_FOR_REAUTH.
- `H3` enforcement (larger of explicit notional vs qty × live price) and `H4` (quantity-only derives notional from live quote).
- 95 unit + integration tests passing in ~2s.
- `pyproject.toml` with setuptools build, console script entry, dev/vibe extras.
- `Makefile` (install, test, lint, format, run-stdio, run-sse, clean).
- `README.md` with quick start, tool surface, mandate schema, gate description, kill switch, integration guide, env var table, architecture diagram.
