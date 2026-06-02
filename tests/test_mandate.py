"""Mandate loader: structural validation + fail-closed behavior."""

from __future__ import annotations

from bybit_mcp.safety.mandate import (
    MANDATE_SCHEMA_VERSION,
    AssetClass,
    InstrumentType,
    load_mandate,
)


def test_load_mandate_returns_none_when_missing(tmp_runtime_root):
    assert load_mandate("bybit") is None


def test_load_mandate_parses_valid(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    m = load_mandate("bybit")
    assert m is not None
    assert m.schema_version == MANDATE_SCHEMA_VERSION
    assert m.hard_caps.max_order_notional_usd == 1000.0
    assert m.hard_caps.max_leverage == 3.0
    assert m.hard_caps.allowed_instruments == (InstrumentType.CRYPTO,)
    assert m.universe.asset_classes == (AssetClass.CRYPTO,)
    assert m.universe.exclude_symbols == ("DOGEUSDT",)
    assert m.consent.account_ref == "acct-0001"
    assert m.flatten_on_halt is False


def test_load_mandate_uppercase_broker_key(write_mandate, sample_mandate_payload):
    write_mandate("ByBit", sample_mandate_payload)
    assert load_mandate("BYBIT") is not None


def test_load_mandate_invalid_json(tmp_runtime_root):
    path = tmp_runtime_root / "live" / "bybit" / "mandate.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not json", encoding="utf-8")
    assert load_mandate("bybit") is None


def test_load_mandate_missing_hard_caps(write_mandate, sample_mandate_payload):
    del sample_mandate_payload["hard_caps"]
    write_mandate("bybit", sample_mandate_payload)
    assert load_mandate("bybit") is None


def test_load_mandate_bad_instrument_type(write_mandate, sample_mandate_payload):
    sample_mandate_payload["hard_caps"]["allowed_instruments"] = ["weird_type"]
    write_mandate("bybit", sample_mandate_payload)
    assert load_mandate("bybit") is None


def test_load_mandate_bad_numeric_field(write_mandate, sample_mandate_payload):
    sample_mandate_payload["hard_caps"]["max_leverage"] = "three"
    write_mandate("bybit", sample_mandate_payload)
    assert load_mandate("bybit") is None


def test_load_mandate_optional_floats_can_be_null(write_mandate, sample_mandate_payload):
    sample_mandate_payload["universe"]["min_market_cap_usd"] = None
    sample_mandate_payload["universe"]["min_avg_daily_volume_usd"] = None
    write_mandate("bybit", sample_mandate_payload)
    m = load_mandate("bybit")
    assert m is not None
    assert m.universe.min_market_cap_usd is None


def test_load_mandate_optional_floats_can_be_number(write_mandate, sample_mandate_payload):
    sample_mandate_payload["universe"]["min_market_cap_usd"] = 1_000_000
    write_mandate("bybit", sample_mandate_payload)
    m = load_mandate("bybit")
    assert m is not None
    assert m.universe.min_market_cap_usd == 1_000_000


def test_load_mandate_flatten_on_halt_default_false(write_mandate, sample_mandate_payload):
    sample_mandate_payload.pop("flatten_on_halt", None)
    write_mandate("bybit", sample_mandate_payload)
    m = load_mandate("bybit")
    assert m is not None
    assert m.flatten_on_halt is False


def test_load_mandate_flatten_on_halt_true(write_mandate, sample_mandate_payload):
    sample_mandate_payload["flatten_on_halt"] = True
    write_mandate("bybit", sample_mandate_payload)
    m = load_mandate("bybit")
    assert m is not None
    assert m.flatten_on_halt is True
