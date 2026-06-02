"""Tests for the runtime-root resolver and broker_dir validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from bybit_mcp.safety.paths import broker_dir, get_runtime_root, live_root


def test_default_runtime_root_is_vibe_trading(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VIBE_RUNTIME_ROOT", raising=False)
    assert get_runtime_root() == Path("~/.vibe-trading").expanduser()


def test_runtime_root_honours_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBE_RUNTIME_ROOT", "/tmp/custom-vibe")
    assert get_runtime_root() == Path("/tmp/custom-vibe")


def test_live_root_is_under_runtime(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBE_RUNTIME_ROOT", "/tmp/rt")
    assert live_root() == Path("/tmp/rt/live")


def test_broker_dir_lowercases_and_strips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VIBE_RUNTIME_ROOT", "/tmp/rt")
    assert broker_dir("  ByBit  ") == Path("/tmp/rt/live/bybit")


def test_broker_dir_rejects_empty():
    with pytest.raises(ValueError, match="must not be empty"):
        broker_dir("")
    with pytest.raises(ValueError, match="must not be empty"):
        broker_dir("   ")


def test_broker_dir_rejects_path_traversal():
    with pytest.raises(ValueError, match="invalid broker key"):
        broker_dir("../etc")
    with pytest.raises(ValueError, match="invalid broker key"):
        broker_dir("a/b")
    with pytest.raises(ValueError, match="invalid broker key"):
        broker_dir("a\\b")
