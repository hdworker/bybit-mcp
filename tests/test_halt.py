"""Kill switch tests."""

from __future__ import annotations

from bybit_mcp.safety.halt import (
    broker_halt_path,
    clear_halt,
    halt_flag_set,
    halt_path,
    read_halt,
    trip_halt,
)


def test_halt_flag_unset(tmp_runtime_root):
    assert halt_flag_set() is False
    assert halt_flag_set("bybit") is False


def test_trip_and_clear_global(tmp_runtime_root):
    trip_halt(by="cli", reason="manual stop")
    assert halt_path().exists()
    assert halt_flag_set() is True
    assert halt_flag_set("bybit") is True  # global always wins
    assert clear_halt() is True
    assert halt_path().exists() is False
    assert halt_flag_set() is False


def test_trip_and_clear_per_broker(tmp_runtime_root):
    trip_halt(by="cli", reason="broker-only stop", broker="bybit")
    assert broker_halt_path("bybit").exists()
    assert halt_flag_set("bybit") is True
    # A per-broker trip only halts THAT broker, not others.
    assert halt_flag_set("okx") is False
    clear_halt(broker="bybit")
    assert broker_halt_path("bybit").exists() is False
    assert halt_flag_set("bybit") is False


def test_clear_returns_false_when_unset(tmp_runtime_root):
    assert clear_halt() is False
    assert clear_halt(broker="bybit") is False


def test_halt_invalid_broker_fails_closed():
    """An invalid broker key (path traversal) MUST read as halted (fail-closed)."""
    assert halt_flag_set("../etc") is True


def test_read_halt_returns_metadata(tmp_runtime_root):
    trip_halt(by="cli", reason="because", broker="bybit")
    payload = read_halt(broker="bybit")
    assert payload is not None
    assert payload["by"] == "cli"
    assert payload["reason"] == "because"
    assert "tripped_at" in payload


def test_read_halt_returns_none_when_unset(tmp_runtime_root):
    assert read_halt() is None
    assert read_halt(broker="bybit") is None


def test_read_halt_returns_empty_dict_on_malformed(tmp_runtime_root):
    """An unreadable sentinel still trips the switch; attribution may be empty."""
    path = broker_halt_path("bybit")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json at all", encoding="utf-8")
    assert halt_flag_set("bybit") is True
    assert read_halt(broker="bybit") == {}
