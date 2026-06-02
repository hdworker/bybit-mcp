"""Tests for the live-action audit ledger."""

from __future__ import annotations

import json
from typing import Any

from bybit_mcp.safety.audit import (
    LiveActionEvent,
    audit_ledger_path,
    write_live_action,
)


def test_write_to_dedicated_ledger(tmp_runtime_root):
    event = LiveActionEvent(
        kind="order_placed", session_id="s1", outcome="accepted",
        server="bybit", remote_tool="bybit_place_order",
    )
    write_live_action(event)
    path = audit_ledger_path()
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["kind"] == "order_placed"
    assert rec["server"] == "bybit"
    assert rec["remote_tool"] == "bybit_place_order"
    assert rec["session_id"] == "s1"


def test_ledger_redacts_secrets_before_writing(tmp_runtime_root):
    event = LiveActionEvent(
        kind="order_placed", session_id="s2", outcome="accepted",
        server="bybit", remote_tool="bybit_place_order",
        broker_request={"category": "linear", "api_key": "supersecret", "qty": "0.001"},
    )
    write_live_action(event)
    rec = json.loads(audit_ledger_path().read_text(encoding="utf-8").strip().splitlines()[-1])
    assert rec["broker_request"]["api_key"] == "[redacted]"
    assert rec["broker_request"]["category"] == "linear"
    assert rec["broker_request"]["qty"] == "0.001"


def test_audit_id_and_ts_auto_generated(tmp_runtime_root):
    event = LiveActionEvent(
        kind="order_rejected", session_id="s3", outcome="blocked",
        server="bybit", remote_tool="bybit_place_order",
    )
    rec = write_live_action(event)
    assert rec["audit_id"].startswith("la_")
    assert "T" in rec["ts"]


def test_event_callback_sink(tmp_runtime_root):
    received: list[tuple[str, dict[str, Any]]] = []

    def cb(name: str, payload: dict[str, Any]) -> None:
        received.append((name, payload))

    event = LiveActionEvent(
        kind="order_placed", session_id="s4", outcome="accepted",
        server="bybit", remote_tool="bybit_place_order",
    )
    rec = write_live_action(event, event_callback=cb)
    assert received == [("live.action", rec)]


def test_trace_writer_sink(tmp_runtime_root):
    written: list[dict[str, Any]] = []

    class TW:
        def write(self, entry: dict[str, Any]) -> None:
            written.append(entry)

    event = LiveActionEvent(
        kind="order_placed", session_id="s5", outcome="accepted",
        server="bybit", remote_tool="bybit_place_order",
    )
    write_live_action(event, trace_writer=TW())
    assert len(written) == 1
    assert written[0]["type"] == "live_action"
    assert written[0]["kind"] == "order_placed"


def test_multiple_records_append(tmp_runtime_root):
    for i in range(3):
        write_live_action(LiveActionEvent(
            kind="order_placed", session_id=f"s{i}", outcome="accepted",
            server="bybit", remote_tool="bybit_place_order",
        ))
    lines = audit_ledger_path().read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    recs = [json.loads(line) for line in lines]
    assert [r["session_id"] for r in recs] == ["s0", "s1", "s2"]
