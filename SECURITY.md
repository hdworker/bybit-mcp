# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in bybit-mcp, please send an email to **hdworker@yandex.ru** with a detailed description. Do **not** open a public issue.

We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation plan within 14 days.

## Threat Model

### What the gate protects against

| Threat | Mitigation |
|---|---|
| Oversized orders | `max_order_notional_usd` cap enforced per-call (H3: larger of explicit notional or qty × live price) |
| Excessive leverage | `max_leverage` structural cap |
| Over-exposure | `max_total_exposure_usd` checked post-trade |
| Unauthorized trading after user revokes | `expires_at` expiry check + `flatten_on_halt` |
| Runaway order loop | `max_trades_per_day` daily counter |
| Account funding abuse | `account_funding_usd` ceiling |
| Trading banned instruments | Exclude-list + allowed instruments + asset classes |
| Accidental order placement | Kill switch (`touch ~/.vibe-trading/live/HALT`) — instant, no LLM cooperation needed |
| Secret leakage in audit logs | Redaction layer strips credentials, PII, account numbers before any sink write |

### What the gate does NOT protect against

| Gap | Workaround |
|---|---|
| Market risk (price moves against you) | Use TP/SL on every position; this is a consent gate, not a risk manager |
| Slippage / partial fills | Broker-side execution quality; gate only checks intent, not fill quality |
| Mandate file tampering (local filesystem) | Ensure file permissions (`chmod 600 mandate.json`); the gate reads the file as-is |
| Bybit API key compromise | Rotate keys immediately; trip the halt sentinel; revoke mandate |
| LLM prompt injection | The gate is fail-closed — no mandate = no orders, regardless of LLM intent |
| Clock skew exploitation | `TimeSync` auto-syncs with Bybit server time; recv_window limits window size |

## Security Best Practices

1. **Never commit `.env`** — it contains your Bybit API key and secret.
2. **Use a dedicated API key** — do not share keys between bybit-mcp and other applications.
3. **Set `max_trades_per_day`** low enough to catch runaway loops (start with 10-50).
4. **Set `expires_at`** — mandate should have a finite lifetime; renew via consent UX.
5. **Monitor the audit ledger** — `<runtime_root>/live/audit.jsonl` records every decision.
6. **Test on testnet first** — set `BYBIT_TESTNET=true` before going live.
7. **Know the kill switch** — `touch ~/.vibe-trading/live/HALT` stops all activity instantly.
