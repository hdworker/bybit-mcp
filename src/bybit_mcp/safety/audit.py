"""Live-action audit ledger for the bybit-mcp channel.

Append-only ledger at ``<runtime_root>/live/audit.jsonl`` — the same file the
Vibe-Trading in-repo ``LiveOrderGuardTool`` writes to, so audit consumers see
a unified stream of live actions across the whole agent regardless of which
gate enforced them.

Every record is redacted FIRST (via :func:`bybit_mcp.safety.redaction.redact_payload`)
so OAuth tokens / API keys / account numbers never reach the ledger.

The redacted record fans out to:

1. **Dedicated ledger** (``audit.jsonl``) — always.
2. **Per-run trace writer** (optional, ``TraceWriterLike`` with ``.write(dict)``).
3. **Surface callback** (optional, ``(event_name, payload)``).

Kinds match Vibe-Trading SPEC §5: ``order_placed``, ``order_cancelled``,
``order_rejected``, ``mandate_committed``, ``breach``, ``halt_tripped``,
``halt_cleared``. Outcomes: ``accepted``, ``filled``, ``rejected``, ``error``,
``blocked``.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from bybit_mcp.safety.paths import live_root
from bybit_mcp.safety.redaction import redact_payload

logger = logging.getLogger(__name__)

_LIVE_ACTION_EVENT = "live.action"
_LIVE_ACTION_TRACE_TYPE = "live_action"
_LEDGER_FILENAME = "audit.jsonl"

LiveActionKind = Literal[
    "order_placed",
    "order_cancelled",
    "order_rejected",
    "mandate_committed",
    "breach",
    "halt_tripped",
    "halt_cleared",
]

LiveActionOutcome = Literal["accepted", "filled", "rejected", "error", "blocked"]


class _TraceWriterLike(Protocol):
    """Structural type for an optional per-run trace sink."""

    def write(self, entry: dict[str, Any]) -> None: ...


EventCallback = Callable[[str, dict[str, Any]], Any]


def _new_audit_id() -> str:
    return f"la_{uuid.uuid4().hex}"


def _utc_now_iso_ms() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def audit_ledger_path() -> Path:
    """Return the path to the dedicated live-action ledger (NOT created here)."""
    return live_root() / _LEDGER_FILENAME


@dataclass(frozen=True)
class LiveActionEvent:
    """One immutable live-action audit record.

    Attributes:
        kind: ``order_placed`` | ``order_cancelled`` | ``order_rejected`` |
            ``mandate_committed`` | ``breach`` | ``halt_tripped`` | ``halt_cleared``.
        session_id: Originating session id.
        outcome: ``accepted`` | ``filled`` | ``rejected`` | ``error`` | ``blocked``.
        server: Origin server / broker key, e.g. ``"bybit"``.
        remote_tool: Broker remote tool name, e.g. ``"bybit_place_order"``.
        intent_normalized: Human-readable normalized intent.
        mandate_snapshot_ref: Which mandate authorized the action.
        consent_record_ref: Which user consent authorized that mandate.
        broker_request: Raw request sent to the broker (redacted before write).
        broker_response: Raw broker response (redacted before write).
        gate_decision: The enforcement gate's verdict.
        error: Error description when ``outcome == "error"``, else ``None``.
        audit_id: Auto-generated unique id (``la_<hex>``).
        ts: ISO-8601 UTC timestamp (ms precision).
    """

    kind: LiveActionKind
    session_id: str
    outcome: LiveActionOutcome
    server: str
    remote_tool: str | None = None
    intent_normalized: str | None = None
    mandate_snapshot_ref: str | None = None
    consent_record_ref: str | None = None
    broker_request: dict[str, Any] | None = None
    broker_response: dict[str, Any] | None = None
    gate_decision: dict[str, Any] | None = None
    error: str | None = None
    audit_id: str = field(default_factory=_new_audit_id)
    ts: str = field(default_factory=_utc_now_iso_ms)

    def to_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "audit_id": self.audit_id,
            "ts": self.ts,
            "session_id": self.session_id,
            "kind": self.kind,
            "intent_normalized": self.intent_normalized,
            "mandate_snapshot_ref": self.mandate_snapshot_ref,
            "consent_record_ref": self.consent_record_ref,
            "broker_request": self.broker_request,
            "broker_response": self.broker_response,
            "outcome": self.outcome,
            "gate_decision": self.gate_decision,
            "server": self.server,
            "remote_tool": self.remote_tool,
            "error": self.error,
        }
        return redact_payload(record)


def write_live_action(
    event: LiveActionEvent,
    *,
    event_callback: EventCallback | None = None,
    trace_writer: _TraceWriterLike | None = None,
) -> dict[str, Any]:
    """Fan a redacted live-action record out to up to three sinks.

    Args:
        event: The live-action event to record.
        event_callback: Optional surface bus ``(event_name, payload)`` callable.
        trace_writer: Optional per-run trace sink with ``.write(dict)``.

    Returns:
        The redacted record dict (identical to what was written to every sink).
    """
    record = event.to_record()

    path = audit_ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(record, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")

    if trace_writer is not None:
        trace_writer.write({"type": _LIVE_ACTION_TRACE_TYPE, **record})

    if event_callback is not None:
        event_callback(_LIVE_ACTION_EVENT, record)

    return record
