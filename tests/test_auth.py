"""HMAC signing + TimeSync tests.

Bybit v5 known-vector: signing payload = ``f"{timestamp}{api_key}{recv_window}{payload_str}"``
→ HMAC-SHA256(secret) → hex string in the ``X-BAPI-SIGN`` header.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import MagicMock, patch

import httpx

from bybit_mcp.client.auth import TimeSync, sign

# ---------------------------------------------------------------------------
# sign()
# ---------------------------------------------------------------------------


def test_sign_matches_rfc_vector():
    """sign() must produce the exact HMAC-SHA256 hex for a known input."""
    secret = "secret"
    ts = 1700000000000
    api_key = "ABCDEF"
    recv_window = 5000
    payload = '{"category":"linear","symbol":"BTCUSDT"}'
    expected = hmac.new(
        secret.encode("utf-8"),
        f"{ts}{api_key}{recv_window}{payload}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert sign(secret, ts, api_key, recv_window, payload) == expected


def test_sign_handles_empty_payload():
    """Empty payload (typical for POST with body) signs over the empty string."""
    secret = "k"
    ts = 1
    api_key = "k"
    rw = 5
    expected = hmac.new(
        b"k",
        b"1k5",
        hashlib.sha256,
    ).hexdigest()
    assert sign(secret, ts, api_key, rw, "") == expected


def test_sign_is_deterministic():
    assert sign("a", 1, "b", 2, "c") == sign("a", 1, "b", 2, "c")


# ---------------------------------------------------------------------------
# TimeSync
# ---------------------------------------------------------------------------


def test_time_sync_computes_delta():
    """TimeSync should compute server_time - local_time after first sync."""
    base_url = "https://api.bybit.com"

    # Mock response: server says it's 1700000000 sec + 500_000_000 ns = 1700000000500 ms.
    server_sec = 1700000000
    server_ms = server_sec * 1000
    local_ms_before = int(time.time() * 1000)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {"retCode": 0, "result": {"timeSecond": str(server_sec), "timeNano": "500000000"}}
    resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.get.return_value = resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)

    with patch("bybit_mcp.client.auth.httpx.Client", return_value=mock_client):
        ts = TimeSync(base_url)
        ts.sync()
        delta_after = ts._state.delta_ms  # computed at sync
        ts.close()

    # delta_ms should be ~server_ms - local_ms_at_sync
    # Allow generous slack (clock moved during the test)
    assert abs(delta_after - (server_ms - local_ms_before)) < 10_000


def test_time_sync_now_ms_uses_synced_delta():
    """now_ms() should return local_clock + delta_ms, not the raw local clock."""
    ts = TimeSync("https://api.bybit.com")
    ts._state.delta_ms = 1234  # pretend server is 1234ms ahead
    ts._state.last_synced_at = time.monotonic()  # mark fresh
    expected = int(time.time() * 1000) + 1234
    assert abs(ts.now_ms() - expected) < 5
    ts.close()
