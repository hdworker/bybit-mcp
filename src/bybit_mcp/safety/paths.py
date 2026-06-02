"""Filesystem layout for the bybit-mcp live channel.

Mirrors Vibe-Trading's ``agent.src.live.paths`` so the same runtime root
(``~/.vibe-trading`` by default, overridable via ``VIBE_RUNTIME_ROOT``) is used
by both the in-repo ``LiveOrderGuardTool`` and the bybit-mcp server, and the
mandate/halt/audit/counter files live in the SAME locations — the bybit-mcp
server writes to the same files, so the native guard, the bybit-mcp guard, and
the human-facing CLI all see the same state.

Layout::

    <runtime_root>/live/<broker>/mandate.json     # committed mandate (0600)
    <runtime_root>/live/<broker>/trade_counter.json
    <runtime_root>/live/HALT                      # global kill switch
    <runtime_root>/live/<broker>/HALT             # per-broker kill switch
    <runtime_root>/live/audit.jsonl               # live-action ledger (append-only)
"""

from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_RUNTIME_ROOT = Path("~/.vibe-trading").expanduser()


def get_runtime_root() -> Path:
    """Return the runtime root, honouring ``VIBE_RUNTIME_ROOT`` if set.

    Returns:
        ``Path`` to the runtime root (NOT created here).
    """
    raw = os.getenv("VIBE_RUNTIME_ROOT")
    if raw:
        return Path(raw).expanduser()
    return _DEFAULT_RUNTIME_ROOT


def live_root() -> Path:
    """Return ``<runtime_root>/live`` (NOT created here)."""
    return get_runtime_root() / "live"


def broker_dir(broker: str) -> Path:
    """Return ``<runtime_root>/live/<broker>`` (NOT created here).

    Raises:
        ValueError: Empty / whitespace / path-traversal / separator in key.
    """
    key = broker.strip().lower()
    if not key:
        raise ValueError("broker key must not be empty")
    if "/" in key or "\\" in key or ".." in key:
        raise ValueError(f"invalid broker key: {broker!r}")
    return live_root() / key
