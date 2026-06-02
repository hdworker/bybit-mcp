"""Shared pytest fixtures for the bybit-mcp test suite."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def tmp_runtime_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ``VIBE_RUNTIME_ROOT`` to a fresh tmp dir for the test."""
    root = tmp_path / "vibe-runtime"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("VIBE_RUNTIME_ROOT", str(root))
    return root


@pytest.fixture
def sample_mandate_payload() -> dict:
    """A canonical, currently-valid mandate for the ``bybit`` broker."""
    expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    return {
        "schema_version": 1,
        "hard_caps": {
            "account_funding_usd": 5000.0,
            "max_order_notional_usd": 1000.0,
            "max_total_exposure_usd": 5000.0,
            "max_leverage": 3.0,
            "allowed_instruments": ["crypto"],
            "max_trades_per_day": 50,
        },
        "universe": {
            "asset_classes": ["crypto"],
            "min_market_cap_usd": None,
            "min_avg_daily_volume_usd": None,
            "exclude_symbols": ["DOGEUSDT"],
        },
        "consent": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "consent_token_sha256": "abc123def456",
            "broker": "bybit",
            "account_ref": "acct-0001",
            "expires_at": expires,
        },
        "flatten_on_halt": False,
    }


@pytest.fixture
def write_mandate(tmp_runtime_root: Path):
    """Helper to write a mandate.json to the broker's runtime dir.

    The broker key is normalized to lower-case + stripped so test files
    match the same path that :func:`load_mandate` resolves.
    """
    def _write(broker: str, payload: dict) -> Path:
        key = broker.strip().lower()
        path = tmp_runtime_root / "live" / key / "mandate.json"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    return _write
