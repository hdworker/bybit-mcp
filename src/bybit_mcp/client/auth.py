"""Bybit v5 authentication.

Bybit v5 signs every private request with HMAC-SHA256 over the canonical
``timestamp + api_key + recv_window + payload_string`` string. The signature
goes into the ``X-BAPI-SIGN`` header.

Signing payload rules (https://bybit-exchange.github.io/docs/v5/guide#authentication):

* For GET requests: payload = sorted query string (``a=1&b=2``)
* For POST requests: payload = raw JSON body string (NOT the dict — must match
  exactly what is sent on the wire)

Time sync: the server clock must be within ``recv_window`` ms of Bybit's clock,
otherwise the request is rejected with error code 10002. We sync against
Bybit's ``/v5/market/time`` endpoint on first use and re-sync every 5 min.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Optional

import httpx

MAINNET_TIME_URL = "https://api.bybit.com/v5/market/time"
TESTNET_TIME_URL = "https://api-testnet.bybit.com/v5/market/time"
SYNC_REFRESH_SECONDS = 300


def sign(secret: str, timestamp_ms: int, api_key: str, recv_window_ms: int, payload: str) -> str:
    """Compute the Bybit v5 signature.

    Args:
        secret: API secret.
        timestamp_ms: Request timestamp in milliseconds.
        api_key: API key.
        recv_window_ms: recv_window in ms.
        payload: Sorted query string for GET, raw JSON body for POST.

    Returns:
        Hex-encoded HMAC-SHA256 signature.
    """
    sign_str = f"{timestamp_ms}{api_key}{recv_window_ms}{payload}"
    mac = hmac.new(
        secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()


@dataclass
class _TimeSync:
    """Cached server-time offset.

    delta_ms = server_time_ms - local_time_ms.
    """

    delta_ms: int = 0
    last_synced_at: float = 0.0
    _lock: Lock = field(default_factory=Lock)

    def is_fresh(self) -> bool:
        return (time.monotonic() - self.last_synced_at) < SYNC_REFRESH_SECONDS

    def get_server_now_ms(self) -> int:
        return int(time.time() * 1000) + self.delta_ms


class TimeSync:
    """Public wrapper. Syncs on first use and on expiry."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._state = _TimeSync()
        self._client: Optional[httpx.Client] = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=5.0)
        return self._client

    def sync(self, force: bool = False) -> None:
        """Sync local clock against Bybit server time.

        Safe to call concurrently — the first caller holds the lock; others
        see fresh state on retry.
        """
        with self._state._lock:
            if not force and self._state.is_fresh():
                return
            url = f"{self._base_url}/v5/market/time"
            try:
                resp = self._http().get(url, timeout=5.0)
                resp.raise_for_status()
                payload = resp.json()
                server_ms = int(payload["result"]["timeSecond"]) * 1000
                local_ms = int(time.time() * 1000)
                self._state.delta_ms = server_ms - local_ms
                self._state.last_synced_at = time.monotonic()
            except Exception:
                # Fallback: assume local clock is correct. Next call will retry.
                self._state.last_synced_at = time.monotonic() - SYNC_REFRESH_SECONDS + 30

    def now_ms(self) -> int:
        """Return current Bybit-server time in ms. Triggers sync if stale."""
        if not self._state.is_fresh():
            self.sync()
        return self._state.get_server_now_ms()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
