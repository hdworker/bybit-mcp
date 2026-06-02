"""Local redaction helper (P10 — keep the audit ledger free of secrets).

A standalone re-implementation of the Vibe-Trading ``src.tools.redaction`` core
(``redact_payload`` / ``is_sensitive_arg``) so this MCP server can write a
compliant audit ledger WITHOUT depending on Vibe-Trading at runtime. The
behaviour is intentionally identical: credential keys (``api_key``,
``authorization``, ``*token*``, ``password``, ``secret``, ``passphrase``, …) and
a curated set of exact account/PII field names (``account_number``,
``routing_number``, ``ssn``, …) are replaced with ``"[redacted]"`` before any
record reaches the ledger or the surface bus.

The opaque ``account_ref`` provenance field is **preserved** (it's the
mandate→consent accountability chain). Any key we don't know about passes
through unchanged. Matching is exact on the curated PII set (never a broad
``"account"`` substring that would clobber the audit record's own
``account_ref``).
"""

from __future__ import annotations

from typing import Any

_REDACTED = "[redacted]"

_PII_EXACT_KEYS: frozenset[str] = frozenset({
    "account_number",
    "account_id",
    "account_no",
    "account_num",
    "brokerage_account_number",
    "brokerage_account_id",
    "account_url",
    "rhs_account_number",
    "ssn",
    "social_security_number",
    "tax_id",
    "taxpayer_id",
    "tin",
    "routing_number",
    "bank_account_number",
})

_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "api_key",
    "authorization",
    "content",
    "env",
    "headers",
    "passphrase",
    "password",
    "secret",
    "token",
}) | _PII_EXACT_KEYS

_SENSITIVE_MARKERS: tuple[str, ...] = ("api_key", "authorization", "password", "secret", "token")


def _fold(name: str) -> str:
    """Return lower-cased alphanumeric-only form of ``name``."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


_FOLDED_SENSITIVE_KEYS: frozenset[str] = frozenset(_fold(k) for k in _SENSITIVE_KEYS)
_FOLDED_MARKERS: tuple[str, ...] = tuple(_fold(m) for m in _SENSITIVE_MARKERS)


def is_sensitive_arg(name: str) -> bool:
    """Return ``True`` if a payload key holds a credential / PII value."""
    normalized = name.strip().lower()
    if normalized in _SENSITIVE_KEYS or any(m in normalized for m in _SENSITIVE_MARKERS):
        return True
    folded = _fold(name)
    return folded in _FOLDED_SENSITIVE_KEYS or any(m in folded for m in _FOLDED_MARKERS)


def redact_payload(obj: Any) -> Any:
    """Recursively replace sensitive values with ``"[redacted]"``.

    The input is never mutated; a deep copy with scrubbed values is returned.
    """
    if isinstance(obj, dict):
        return {
            key: _REDACTED if is_sensitive_arg(str(key)) else redact_payload(item)
            for key, item in obj.items()
        }
    if isinstance(obj, list):
        return [redact_payload(item) for item in obj]
    if isinstance(obj, tuple):
        return tuple(redact_payload(item) for item in obj)
    return obj
