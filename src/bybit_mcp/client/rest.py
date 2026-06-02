"""Bybit v5 REST client.

Async-first (httpx.AsyncClient). Public endpoints work without API keys;
private endpoints require ``api_key`` + ``api_secret`` and return signed
requests via :mod:`bybit_mcp.client.auth`.

The client is intentionally thin — it knows the URL shape and signs requests,
but it does not enforce any business logic. The safety layer (mandate, halt,
audit, daily count) lives in :mod:`bybit_mcp.safety` and is invoked from the
MCP tool wrappers, not from the client itself.

Test surface: :func:`request` accepts a transport argument so unit tests can
inject a mock httpx client without going over the network.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

from bybit_mcp.client.auth import TimeSync, sign

logger = logging.getLogger(__name__)

MAINNET_BASE = "https://api.bybit.com"
TESTNET_BASE = "https://api-testnet.bybit.com"


class BybitError(Exception):
    """Base error for Bybit client + transport failures."""

    def __init__(self, message: str, *, ret_code: int = 0, status: int = 0) -> None:
        super().__init__(message)
        self.ret_code = ret_code
        self.status = status


class BybitAPIError(BybitError):
    """Bybit returned a non-zero retCode envelope."""

    def __init__(self, ret_code: int, ret_msg: str, ret_ext_info: dict | None = None) -> None:
        super().__init__(f"bybit api error {ret_code}: {ret_msg}", ret_code=ret_code)
        self.ret_msg = ret_msg
        self.ret_ext_info = ret_ext_info or {}


class BybitAuthError(BybitAPIError):
    """Auth-related failure (10003 invalid sign, 10004 bad api key, ...)."""


class BybitTransportError(BybitError):
    """Network / timeout / 5xx."""


@dataclass
class BybitConfig:
    """Client configuration.

    Attributes:
        testnet: True = testnet (https://api-testnet.bybit.com).
        api_key: API key (empty = public endpoints only).
        api_secret: API secret.
        recv_window_ms: recv_window for signed requests.
        http_timeout: Per-request timeout in seconds.
    """

    testnet: bool = False
    api_key: str = ""
    api_secret: str = ""
    recv_window_ms: int = 5000
    http_timeout: float = 10.0

    @property
    def base_url(self) -> str:
        return TESTNET_BASE if self.testnet else MAINNET_BASE

    @classmethod
    def from_env(cls) -> "BybitConfig":
        return cls(
            testnet=os.getenv("BYBIT_TESTNET", "false").lower() in {"1", "true", "yes", "on"},
            api_key=os.getenv("BYBIT_API_KEY", "").strip(),
            api_secret=os.getenv("BYBIT_API_SECRET", "").strip(),
            recv_window_ms=int(os.getenv("BYBIT_RECV_WINDOW", "5000")),
            http_timeout=float(os.getenv("BYBIT_HTTP_TIMEOUT", "10")),
        )

    @property
    def has_auth(self) -> bool:
        return bool(self.api_key) and bool(self.api_secret)


class BybitClient:
    """Async Bybit v5 REST client.

    Use as an async context manager::

        async with BybitClient(cfg) as client:
            tickers = await client.get_tickers(category="linear", symbol="BTCUSDT")
    """

    def __init__(
        self,
        config: BybitConfig | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._config = config or BybitConfig.from_env()
        self._time_sync = TimeSync(self._config.base_url)
        self._transport = transport
        self._client: httpx.AsyncClient | None = None

    @property
    def config(self) -> BybitConfig:
        return self._config

    async def __aenter__(self) -> "BybitClient":
        kwargs: dict[str, Any] = {"timeout": self._config.http_timeout}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        self._client = httpx.AsyncClient(**kwargs)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._time_sync.close()

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("BybitClient must be used as an async context manager")
        return self._client

    # ---- Core request ------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        signed: bool = False,
    ) -> dict[str, Any]:
        """Make a single HTTP request and return the unwrapped result.

        Args:
            method: HTTP method (GET / POST).
            path: API path (e.g. ``/v5/market/kline``).
            params: Query parameters.
            body: JSON body for POST.
            signed: Whether to attach auth headers.

        Returns:
            ``response.result`` on success.

        Raises:
            BybitAPIError: retCode != 0.
            BybitTransportError: network / HTTP 5xx / timeout.
        """
        url = f"{self._config.base_url}{path}"
        params = dict(params or {})
        body = dict(body or {})

        headers: dict[str, str] = {"User-Agent": "bybit-mcp/0.1.0"}
        if signed:
            self._time_sync.sync()
            ts = self._time_sync.now_ms()
            params_sorted = self._canonical_query(params)
            body_str = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else ""
            payload_str = params_sorted if method.upper() == "GET" else body_str
            signature = sign(
                self._config.api_secret,
                ts,
                self._config.api_key,
                self._config.recv_window_ms,
                payload_str,
            )
            headers.update(
                {
                    "X-BAPI-API-KEY": self._config.api_key,
                    "X-BAPI-TIMESTAMP": str(ts),
                    "X-BAPI-RECV-WINDOW": str(self._config.recv_window_ms),
                    "X-BAPI-SIGN": signature,
                    "Content-Type": "application/json",
                }
            )

        try:
            if method.upper() == "GET":
                resp = await self._require_client().get(
                    url, params=params, headers=headers,
                )
            elif method.upper() == "POST":
                resp = await self._require_client().post(
                    url, params=params if method.upper() == "GET" else None,
                    content=json.dumps(body) if body else None,
                    headers=headers,
                )
            else:
                raise ValueError(f"unsupported method {method!r}")
        except httpx.TimeoutException as exc:
            raise BybitTransportError(f"bybit request timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            raise BybitTransportError(f"bybit transport error: {exc}") from exc

        if resp.status_code >= 500:
            raise BybitTransportError(
                f"bybit 5xx: {resp.status_code} {resp.text[:200]}",
                status=resp.status_code,
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise BybitTransportError(
                f"bybit returned non-json: {resp.text[:200]}",
                status=resp.status_code,
            ) from exc

        ret_code = int(data.get("retCode", 0))
        ret_msg = str(data.get("retMsg", ""))
        if ret_code != 0:
            if ret_code in {10003, 10004, 10005}:
                raise BybitAuthError(ret_code, ret_msg, data.get("retExtInfo"))
            raise BybitAPIError(ret_code, ret_msg, data.get("retExtInfo"))

        return data.get("result") or {}

    @staticmethod
    def _canonical_query(params: Mapping[str, Any]) -> str:
        """Bybit expects query string params sorted alphabetically by key."""
        if not params:
            return ""
        items = []
        for k in sorted(params.keys()):
            v = params[k]
            if v is None or v == "":
                continue
            items.append(f"{k}={v}")
        return "&".join(items)

    # ---- Public: market ----------------------------------------------------

    async def get_kline(
        self,
        *,
        category: str,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> list[list[Any]]:
        """Fetch kline. Returns raw ``[ts, o, h, l, c, v, turnover]`` rows."""
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": max(1, min(int(limit), 1000)),
        }
        if start_ms is not None:
            params["start"] = int(start_ms)
        if end_ms is not None:
            params["end"] = int(end_ms)
        result = await self.request("GET", "/v5/market/kline", params=params, signed=False)
        return list(result.get("list") or [])

    async def get_orderbook(
        self, *, category: str, symbol: str, limit: int = 50,
    ) -> dict[str, Any]:
        """L2 order book snapshot."""
        params = {
            "category": category,
            "symbol": symbol,
            "limit": max(1, min(int(limit), 200)),
        }
        return await self.request("GET", "/v5/market/orderbook", params=params, signed=False)

    async def get_tickers(
        self, *, category: str, symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Tickers for a category, optionally filtered by symbol."""
        params: dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        result = await self.request("GET", "/v5/market/tickers", params=params, signed=False)
        return list(result.get("list") or [])

    async def get_funding_history(
        self,
        *,
        category: str,
        symbol: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "limit": max(1, min(int(limit), 200)),
        }
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        result = await self.request("GET", "/v5/market/funding/history", params=params, signed=False)
        return list(result.get("list") or [])

    async def get_open_interest(
        self, *, category: str, symbol: str, interval_time: str = "5min", limit: int = 50,
    ) -> list[dict[str, Any]]:
        params = {
            "category": category,
            "symbol": symbol,
            "intervalTime": interval_time,
            "limit": max(1, min(int(limit), 200)),
        }
        result = await self.request("GET", "/v5/market/open-interest", params=params, signed=False)
        return list(result.get("list") or [])

    async def get_instruments_info(
        self, *, category: str, symbol: str | None = None, limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": max(1, min(int(limit), 1000))}
        if symbol:
            params["symbol"] = symbol
        result = await self.request("GET", "/v5/market/instruments-info", params=params, signed=False)
        return list(result.get("list") or [])

    async def get_public_trade_history(
        self, *, category: str, symbol: str, limit: int = 60,
    ) -> list[list[Any]]:
        params = {"category": category, "symbol": symbol, "limit": max(1, min(int(limit), 1000))}
        result = await self.request("GET", "/v5/market/recent-trade", params=params, signed=False)
        return list(result.get("list") or [])

    # ---- Private: account --------------------------------------------------

    async def get_wallet_balance(
        self, *, account_type: str = "UNIFIED", coins: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"accountType": account_type}
        if coins:
            params["coin"] = ",".join(coins)
        result = await self.request(
            "GET", "/v5/account/wallet-balance", params=params, signed=True,
        )
        return list(result.get("list") or [])

    async def get_positions(
        self,
        *,
        category: str,
        symbol: str | None = None,
        settle_coin: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": max(1, min(int(limit), 200))}
        if symbol:
            params["symbol"] = symbol
        if settle_coin:
            params["settleCoin"] = settle_coin
        result = await self.request(
            "GET", "/v5/position/list", params=params, signed=True,
        )
        return list(result.get("list") or [])

    async def set_leverage(
        self, *, category: str, symbol: str, leverage: int,
    ) -> dict[str, Any]:
        body = {"category": category, "symbol": symbol, "leverage": str(int(leverage))}
        return await self.request("POST", "/v5/position/set-leverage", body=body, signed=True)

    # ---- Private: order ----------------------------------------------------

    async def create_order(
        self,
        *,
        category: str,
        symbol: str,
        side: str,
        order_type: str,
        qty: str,
        price: str | None = None,
        time_in_force: str | None = None,
        reduce_only: bool | None = None,
        order_link_id: str | None = None,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        position_idx: int | None = None,
        slippage_tolerance_type: str | None = None,
        slippage_tolerance: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": str(qty),
        }
        if price is not None:
            body["price"] = str(price)
        if time_in_force is not None:
            body["timeInForce"] = time_in_force
        if reduce_only is not None:
            body["reduceOnly"] = bool(reduce_only)
        if order_link_id is not None:
            body["orderLinkId"] = order_link_id
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
        if position_idx is not None:
            body["positionIdx"] = int(position_idx)
        if slippage_tolerance_type is not None:
            body["slippageToleranceType"] = slippage_tolerance_type
        if slippage_tolerance is not None:
            body["slippageTolerance"] = str(slippage_tolerance)

        return await self.request("POST", "/v5/order/create", body=body, signed=True)

    async def amend_order(
        self,
        *,
        category: str,
        symbol: str,
        order_id: str | None = None,
        order_link_id: str | None = None,
        qty: str | None = None,
        price: str | None = None,
        take_profit: str | None = None,
        stop_loss: str | None = None,
    ) -> dict[str, Any]:
        if not order_id and not order_link_id:
            raise ValueError("amend_order requires order_id or order_link_id")
        body: dict[str, Any] = {"category": category, "symbol": symbol}
        if order_id:
            body["orderId"] = order_id
        if order_link_id:
            body["orderLinkId"] = order_link_id
        if qty is not None:
            body["qty"] = str(qty)
        if price is not None:
            body["price"] = str(price)
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
        return await self.request("POST", "/v5/order/amend", body=body, signed=True)

    async def cancel_order(
        self,
        *,
        category: str,
        symbol: str,
        order_id: str | None = None,
        order_link_id: str | None = None,
    ) -> dict[str, Any]:
        if not order_id and not order_link_id:
            raise ValueError("cancel_order requires order_id or order_link_id")
        body: dict[str, Any] = {"category": category, "symbol": symbol}
        if order_id:
            body["orderId"] = order_id
        if order_link_id:
            body["orderLinkId"] = order_link_id
        return await self.request("POST", "/v5/order/cancel", body=body, signed=True)

    async def cancel_all_orders(self, *, category: str, symbol: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"category": category}
        if symbol:
            body["symbol"] = symbol
        return await self.request("POST", "/v5/order/cancel-all", body=body, signed=True)

    async def get_open_orders(
        self, *, category: str, symbol: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": max(1, min(int(limit), 200))}
        if symbol:
            params["symbol"] = symbol
        result = await self.request("GET", "/v5/order/realtime", params=params, signed=True)
        return list(result.get("list") or [])

    async def get_order_history(
        self,
        *,
        category: str,
        symbol: str | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"category": category, "limit": max(1, min(int(limit), 200))}
        if symbol:
            params["symbol"] = symbol
        if start_ms is not None:
            params["startTime"] = int(start_ms)
        if end_ms is not None:
            params["endTime"] = int(end_ms)
        result = await self.request("GET", "/v5/order/history", params=params, signed=True)
        return list(result.get("list") or [])

    async def set_trading_stop(
        self,
        *,
        category: str,
        symbol: str,
        position_idx: int = 0,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        tpsl_mode: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "category": category, "symbol": symbol, "positionIdx": int(position_idx),
        }
        if take_profit is not None:
            body["takeProfit"] = str(take_profit)
        if stop_loss is not None:
            body["stopLoss"] = str(stop_loss)
        if tpsl_mode is not None:
            body["tpslMode"] = tpsl_mode
        return await self.request("POST", "/v5/position/trading-stop", body=body, signed=True)
