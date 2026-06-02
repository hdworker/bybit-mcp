"""Kill switch for the bybit-mcp live channel.

Filesystem-layer kill switch (independent of the LLM cooperating). The
enforcement gate calls :func:`halt_flag_set` before every live order so the
halt works even if the agent loop is wedged, the model is looping, or the SSE
bus is down.

Mirrors Vibe-Trading's ``src.live.halt`` semantics exactly:

* Global sentinel: ``<runtime_root>/live/HALT`` halts ALL brokers.
* Per-broker sentinel: ``<runtime_root>/live/<broker>/HALT`` halts one broker.
* Sentinel payload is a small JSON object for audit attribution; the file's
  *existence* is what enforces the halt, malformed JSON is still tripped
  (fail-closed).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bybit_mcp.safety.paths import broker_dir, live_root

logger = logging.getLogger(__name__)

_HALT_FILENAME = "HALT"
_VALID_BY = ("cli", "frontend", "file")


def halt_path() -> Path:
    """Return the global kill-switch sentinel path (NOT created here)."""
    return live_root() / _HALT_FILENAME


def broker_halt_path(broker: str) -> Path:
    """Return the per-broker kill-switch sentinel path (NOT created here)."""
    return broker_dir(broker) / _HALT_FILENAME


def trip_halt(by: str, reason: str, broker: str | None = None) -> Path:
    """Trip the kill switch (atomic write, idempotent).

    Args:
        by: Trip source (``cli`` / ``frontend`` / ``file``).
        reason: Human-readable reason recorded in the sentinel.
        broker: ``None`` = global, otherwise per-broker.

    Returns:
        The path to the sentinel that was written.
    """
    path = broker_halt_path(broker) if broker is not None else halt_path()
    payload: dict[str, Any] = {
        "tripped_at": datetime.now(timezone.utc).isoformat(),
        "by": by,
        "reason": reason,
    }
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    logger.warning("bybit-mcp kill switch tripped (broker=%s, by=%s): %s", broker or "*", by, reason)
    return path


def clear_halt(broker: str | None = None) -> bool:
    """Clear a tripped kill switch by deleting its sentinel.

    Returns:
        ``True`` if a sentinel existed and was removed, ``False`` otherwise.
    """
    path = broker_halt_path(broker) if broker is not None else halt_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    logger.warning("bybit-mcp kill switch cleared (broker=%s)", broker or "*")
    return True


def halt_flag_set(broker: str | None = None) -> bool:
    """Return whether live trading is halted (pure filesystem check).

    The global sentinel always wins: if ``<runtime_root>/live/HALT`` exists,
    this returns ``True`` for every broker. When the global is unset and a
    broker key is given, the per-broker sentinel is consulted too. An invalid
    broker key returns ``True`` (fail-closed: a malformed key must not trade).
    """
    if halt_path().exists():
        return True
    if broker is None:
        return False
    try:
        return broker_halt_path(broker).exists()
    except ValueError:
        return True


def read_halt(broker: str | None = None) -> dict[str, Any] | None:
    """Read sentinel metadata for a tripped kill switch, or ``None`` if absent."""
    path = broker_halt_path(broker) if broker is not None else halt_path()
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
