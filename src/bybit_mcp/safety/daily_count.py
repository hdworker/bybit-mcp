"""Per-broker daily order counter (UTC calendar day, atomic write).

Mirrors Vibe-Trading's ``src.live.daily_count`` semantics. Advisory only —
the broker enforces the real ceiling — so any read failure reads as ``0``
(fail-open on the count only, never on the order).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from bybit_mcp.safety.paths import broker_dir

_COUNTER_FILENAME = "trade_counter.json"


def _counter_path(broker: str):
    return broker_dir(broker) / _COUNTER_FILENAME


def _utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def read_daily_count(broker: str) -> int:
    """Return today's order count for ``broker`` (UTC rollover; 0 on any miss)."""
    path = _counter_path(broker)
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if not isinstance(raw, dict) or raw.get("date") != _utc_today():
        return 0
    try:
        return int(raw.get("count", 0))
    except (TypeError, ValueError):
        return 0


def increment_daily_count(broker: str) -> int:
    """Persist ``broker``'s incremented count for today (atomic write).

    Returns:
        The new count.
    """
    today = _utc_today()
    count = read_daily_count(broker) + 1
    path = _counter_path(broker)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(
        json.dumps({"date": today, "count": count}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return count
