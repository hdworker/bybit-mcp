"""Extractor tests: Bybit place_order / amend_order → OrderIntent."""

from __future__ import annotations

import pytest

from bybit_mcp.client.enums import CategoryV5
from bybit_mcp.safety.extractors import (
    extract_amend_order_intent,
    extract_place_order_intent,
)
from bybit_mcp.safety.mandate import AssetClass, InstrumentType

# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------


def test_place_order_market_buy():
    intent = extract_place_order_intent({
        "category": "linear", "symbol": "BTCUSDT", "side": "Buy",
        "orderType": "Market", "qty": "0.001",
    })
    assert intent is not None
    assert intent.symbol == "BTCUSDT"
    assert intent.side == "buy"
    assert intent.quantity == pytest.approx(0.001)
    assert intent.notional_usd is None
    assert intent.instrument_type == InstrumentType.CRYPTO
    assert intent.asset_class == AssetClass.CRYPTO
    assert intent.category == CategoryV5.LINEAR


def test_place_order_limit_sell():
    intent = extract_place_order_intent({
        "category": "linear", "symbol": "ETHUSDT", "side": "Sell",
        "orderType": "Limit", "qty": "1.5", "price": "3200",
    })
    assert intent is not None
    assert intent.side == "sell"
    assert intent.symbol == "ETHUSDT"
    assert intent.quantity == pytest.approx(1.5)


def test_place_order_with_explicit_notional():
    intent = extract_place_order_intent({
        "category": "linear", "symbol": "BTCUSDT", "side": "Buy",
        "orderType": "Market", "qty": "0.001", "notional_usd": "65.0",
    })
    assert intent is not None
    assert intent.notional_usd == pytest.approx(65.0)


def test_place_order_missing_symbol_returns_none():
    assert extract_place_order_intent({"side": "Buy", "qty": "0.001"}) is None


def test_place_order_missing_side_returns_none():
    assert extract_place_order_intent({"symbol": "BTCUSDT", "qty": "0.001"}) is None


def test_place_order_invalid_side_returns_none():
    assert extract_place_order_intent({
        "symbol": "BTCUSDT", "side": "Long", "qty": "0.001"
    }) is None


def test_place_order_nonpositive_qty_returns_none():
    assert extract_place_order_intent({
        "symbol": "BTCUSDT", "side": "Buy", "qty": "0",
    }) is None
    assert extract_place_order_intent({
        "symbol": "BTCUSDT", "side": "Buy", "qty": "-1",
    }) is None


def test_place_order_nonpositive_notional_returns_none():
    assert extract_place_order_intent({
        "symbol": "BTCUSDT", "side": "Buy", "qty": "0.001", "notional_usd": "0",
    }) is None


def test_place_order_bad_category_defaults_to_linear():
    intent = extract_place_order_intent({
        "category": "weird_category", "symbol": "BTCUSDT", "side": "Buy", "qty": "0.001",
    })
    assert intent is not None
    assert intent.category == CategoryV5.LINEAR


# ---------------------------------------------------------------------------
# amend_order
# ---------------------------------------------------------------------------


def test_amend_order_increase_size():
    intent = extract_amend_order_intent({
        "category": "linear", "symbol": "BTCUSDT", "side": "Buy",
        "new_qty": "0.5",
    })
    assert intent is not None
    assert intent.quantity == pytest.approx(0.5)


def test_amend_order_missing_symbol_returns_none():
    assert extract_amend_order_intent({"side": "Buy", "new_qty": "0.1"}) is None


def test_amend_order_missing_side_returns_none():
    """Without side the gate cannot determine if it's an up or down size."""
    assert extract_amend_order_intent({"symbol": "BTCUSDT", "new_qty": "0.1"}) is None
