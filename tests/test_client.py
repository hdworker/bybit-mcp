"""Bybit REST client tests (respx-mocked httpx)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from bybit_mcp.client.auth import TimeSync
from bybit_mcp.client.rest import (
    BybitAPIError,
    BybitAuthError,
    BybitClient,
    BybitConfig,
    BybitTransportError,
)

MAINNET = "https://api.bybit.com"


def _ok_envelope(result: Any) -> dict[str, Any]:
    return {"retCode": 0, "retMsg": "OK", "result": result, "time": 1700000000000}


def _err_envelope(ret_code: int, ret_msg: str) -> dict[str, Any]:
    return {"retCode": ret_code, "retMsg": ret_msg, "result": {}, "time": 1700000000000}


@pytest.fixture
def cfg() -> BybitConfig:
    return BybitConfig(
        testnet=False,
        api_key="testkey",
        api_secret="testsecret",
        recv_window_ms=5000,
        http_timeout=5.0,
    )


@pytest.fixture
def client(cfg: BybitConfig):
    # Disable time sync network calls in tests.
    TimeSync.sync = lambda self: None  # type: ignore[assignment]
    return BybitClient(cfg)


# ---------------------------------------------------------------------------
# Public market calls (no signing)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_kline_public(client: BybitClient):
    body = _ok_envelope({
        "symbol": "BTCUSDT",
        "category": "linear",
        "list": [
            ["1700000000000", "65000", "65100", "64900", "65050", "12.5", "812500"],
        ],
    })
    with respx.mock(base_url=MAINNET) as mock:
        route = mock.get("/v5/market/kline").mock(return_value=httpx.Response(200, json=body))
        async with client as c:
            rows = await c.get_kline(category="linear", symbol="BTCUSDT", interval="5")
    assert route.called
    assert rows == [["1700000000000", "65000", "65100", "64900", "65050", "12.5", "812500"]]


@pytest.mark.asyncio
async def test_get_tickers_filters_by_symbol(client: BybitClient):
    body = _ok_envelope({
        "list": [{"symbol": "BTCUSDT", "lastPrice": "65000", "volume24h": "1234"}],
    })
    with respx.mock(base_url=MAINNET) as mock:
        route = mock.get("/v5/market/tickers").mock(return_value=httpx.Response(200, json=body))
        async with client as c:
            rows = await c.get_tickers(category="linear", symbol="BTCUSDT")
    assert route.called
    assert rows[0]["symbol"] == "BTCUSDT"


@pytest.mark.asyncio
async def test_get_instruments_info(client: BybitClient):
    body = _ok_envelope({
        "list": [{"symbol": "BTCUSDT", "lotSizeFilter": {"qtyStep": "0.001"}}],
    })
    with respx.mock(base_url=MAINNET) as mock:
        route = mock.get("/v5/market/instruments-info").mock(
            return_value=httpx.Response(200, json=body)
        )
        async with client as c:
            rows = await c.get_instruments_info(category="linear", symbol="BTCUSDT")
    assert route.called
    assert rows[0]["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Private signed calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signed_request_attaches_auth_headers(client: BybitClient):
    body = _ok_envelope({
        "list": [{"accountType": "UNIFIED", "totalEquity": "10000"}],
    })
    with respx.mock(base_url=MAINNET) as mock:
        route = mock.get("/v5/account/wallet-balance").mock(
            return_value=httpx.Response(200, json=body)
        )
        async with client as c:
            rows = await c.get_wallet_balance(account_type="UNIFIED")
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-BAPI-API-KEY"] == "testkey"
    assert request.headers["X-BAPI-TIMESTAMP"]
    assert request.headers["X-BAPI-RECV-WINDOW"] == "5000"
    assert request.headers["X-BAPI-SIGN"]
    assert rows[0]["accountType"] == "UNIFIED"


@pytest.mark.asyncio
async def test_signed_post_sends_body_with_signature(client: BybitClient):
    body = _ok_envelope({
        "orderId": "1234567890", "orderLinkId": "abc-001",
    })
    with respx.mock(base_url=MAINNET) as mock:
        route = mock.post("/v5/order/create").mock(
            return_value=httpx.Response(200, json=body)
        )
        async with client as c:
            result = await c.create_order(
                category="linear", symbol="BTCUSDT", side="Buy",
                order_type="Market", qty="0.001",
            )
    assert route.called
    request = route.calls.last.request
    assert request.headers["X-BAPI-SIGN"]
    payload = json.loads(request.content)
    assert payload["symbol"] == "BTCUSDT"
    assert payload["side"] == "Buy"
    assert payload["qty"] == "0.001"
    assert result["orderId"] == "1234567890"


# ---------------------------------------------------------------------------
# Error envelope handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retcode_nonzero_raises_api_error(client: BybitClient):
    body = _err_envelope(10001, "internal error")
    with respx.mock(base_url=MAINNET) as mock:
        mock.get("/v5/market/kline").mock(return_value=httpx.Response(200, json=body))
        async with client as c:
            with pytest.raises(BybitAPIError) as exc_info:
                await c.get_kline(category="linear", symbol="BTCUSDT", interval="5")
    assert exc_info.value.ret_code == 10001
    assert "internal error" in str(exc_info.value)


@pytest.mark.asyncio
async def test_signature_error_raises_auth_error(client: BybitClient):
    body = _err_envelope(10004, "invalid api key")
    with respx.mock(base_url=MAINNET) as mock:
        mock.get("/v5/account/wallet-balance").mock(
            return_value=httpx.Response(200, json=body)
        )
        async with client as c:
            with pytest.raises(BybitAuthError):
                await c.get_wallet_balance()


@pytest.mark.asyncio
async def test_5xx_raises_transport_error(client: BybitClient):
    with respx.mock(base_url=MAINNET) as mock:
        mock.get("/v5/market/kline").mock(
            return_value=httpx.Response(502, text="bad gateway")
        )
        async with client as c:
            with pytest.raises(BybitTransportError):
                await c.get_kline(category="linear", symbol="BTCUSDT", interval="5")


@pytest.mark.asyncio
async def test_non_json_response_raises_transport_error(client: BybitClient):
    with respx.mock(base_url=MAINNET) as mock:
        mock.get("/v5/market/kline").mock(
            return_value=httpx.Response(200, text="not json")
        )
        async with client as c:
            with pytest.raises(BybitTransportError):
                await c.get_kline(category="linear", symbol="BTCUSDT", interval="5")


# ---------------------------------------------------------------------------
# Testnet URL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_testnet_uses_testnet_base():
    cfg = BybitConfig(testnet=True, api_key="k", api_secret="s")
    TimeSync.sync = lambda self: None  # type: ignore[assignment]
    c = BybitClient(cfg)
    body = _ok_envelope({"list": [{"symbol": "BTCUSDT"}]})
    with respx.mock(base_url="https://api-testnet.bybit.com") as mock:
        route = mock.get("/v5/market/tickers").mock(
            return_value=httpx.Response(200, json=body)
        )
        async with c as cc:
            rows = await cc.get_tickers(category="linear", symbol="BTCUSDT")
    assert route.called
    assert rows[0]["symbol"] == "BTCUSDT"


# ---------------------------------------------------------------------------
# Symbol normalisation
# ---------------------------------------------------------------------------


def test_to_bybit_symbol_basic():
    from bybit_mcp.client.enums import to_bybit_symbol
    assert to_bybit_symbol("BTC-USDT") == "BTCUSDT"
    assert to_bybit_symbol("eth_usdt") == "ETHUSDT"
    assert to_bybit_symbol("BTCUSDT") == "BTCUSDT"
    with pytest.raises(ValueError):
        to_bybit_symbol("")


def test_from_bybit_symbol():
    from bybit_mcp.client.enums import from_bybit_symbol
    assert from_bybit_symbol("BTCUSDT") == "BTC-USDT"
    assert from_bybit_symbol("ETHUSDC") == "ETH-USDC"
    assert from_bybit_symbol("BTCUSDC") == "BTC-USDC"
