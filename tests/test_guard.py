"""The 6-step fail-closed mandate gate."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from bybit_mcp.client.enums import CategoryV5
from bybit_mcp.safety.extractors import OrderIntent
from bybit_mcp.safety.guard import (
    DECISION_ALLOW,
    DECISION_DENY,
    DECISION_PAUSE,
    MandateGate,
)
from bybit_mcp.safety.halt import trip_halt
from bybit_mcp.safety.mandate import AssetClass, InstrumentType


def _ok_intent(qty: float | None = None, notional: float | None = None) -> OrderIntent:
    return OrderIntent(
        symbol="BTCUSDT", side="buy",
        notional_usd=notional, quantity=qty,
        instrument_type=InstrumentType.CRYPTO, asset_class=AssetClass.CRYPTO,
        category=CategoryV5.LINEAR,
    )


# ---------------------------------------------------------------------------
# Step 1: load_mandate
# ---------------------------------------------------------------------------


def test_no_mandate_denies(tmp_runtime_root):
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_DENY
    assert "mandate" in d.checked_limits


def test_wrong_schema_denies(write_mandate, sample_mandate_payload):
    sample_mandate_payload["schema_version"] = 999
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_DENY


# ---------------------------------------------------------------------------
# Step 2: expiry
# ---------------------------------------------------------------------------


def test_expired_mandate_pauses_for_reauth(write_mandate, sample_mandate_payload):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    sample_mandate_payload["consent"]["expires_at"] = past
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_PAUSE
    assert "expiry" in d.checked_limits


def test_unparseable_expiry_pauses_for_reauth(write_mandate, sample_mandate_payload):
    sample_mandate_payload["consent"]["expires_at"] = "not-a-date"
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_PAUSE


# ---------------------------------------------------------------------------
# Step 3: halt
# ---------------------------------------------------------------------------


def test_halt_flag_denies(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    trip_halt(by="cli", reason="manual", broker="bybit")
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_DENY
    assert "halt_flag" in d.checked_limits


def test_global_halt_denies(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    trip_halt(by="cli", reason="global")  # no broker → global
    g = MandateGate("bybit", session_id="s")
    d = g.check("bybit_place_order", {}, _ok_intent())
    assert d.decision == DECISION_DENY


# ---------------------------------------------------------------------------
# Step 5: quantity → notional
# ---------------------------------------------------------------------------


def test_quantity_only_without_quote_lookup_fails_closed(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")  # no quote_lookup
    intent = _ok_intent(qty=0.5)  # quantity, no notional
    d = g.check("bybit_place_order", {}, intent)
    # Fails closed at step 5: cannot price the quantity.
    assert d.decision == DECISION_DENY
    assert "quote" in d.checked_limits


def test_quantity_with_quote_derives_notional(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s", quote_lookup=lambda s, c: 60_000.0)
    intent = _ok_intent(qty=0.01)  # implies 600 USD
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW
    assert d.intent is not None
    assert d.intent.notional_usd == pytest.approx(600.0)


def test_quantity_and_notional_uses_larger(write_mandate, sample_mandate_payload):
    """H3: enforce the LARGER of explicit notional and quantity × price."""
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s", quote_lookup=lambda s, c: 60_000.0)
    intent = _ok_intent(qty=0.01, notional=10.0)  # qty implies 600, notional says 10
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW
    assert d.intent is not None
    assert d.intent.notional_usd == pytest.approx(600.0)  # larger wins


def test_quantity_and_notional_explicit_wins_when_larger(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s", quote_lookup=lambda s, c: 60_000.0)
    intent = _ok_intent(qty=0.001, notional=500.0)  # qty implies 60, explicit says 500
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW
    assert d.intent is not None
    assert d.intent.notional_usd == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Step 6: check_mandate
# ---------------------------------------------------------------------------


def test_over_notional_pauses_for_reauth(write_mandate, sample_mandate_payload):
    """Quantitative breach → PAUSE_FOR_REAUTH (consent layer can offer widen)."""
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=2000.0)  # cap is 1000
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_PAUSE
    assert d.breach is not None
    assert d.breach.limit == "max_order_notional_usd"
    assert d.breach.kind == "quantitative"


def test_over_exposure_pauses_for_reauth(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=4000.0)  # cap is 5000 but order is 4000
    # Order notional = 4000 ≤ cap 5000 → passes exposure on isolated basis
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_PAUSE  # actually fails notional first
    assert d.breach.limit == "max_order_notional_usd"


def test_exclude_list_denies(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = OrderIntent(
        symbol="DOGEUSDT", side="buy",
        notional_usd=100.0, quantity=None,
        instrument_type=InstrumentType.CRYPTO, asset_class=AssetClass.CRYPTO,
        category=CategoryV5.LINEAR,
    )
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_DENY
    assert d.breach is not None
    assert d.breach.kind == "universe"
    assert d.breach.limit == "exclude_symbols"


def test_disallowed_instrument_denies(write_mandate, sample_mandate_payload):
    sample_mandate_payload["hard_caps"]["allowed_instruments"] = ["equity"]
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=100.0)
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_DENY
    assert d.breach is not None
    assert d.breach.kind == "instrument"


def test_disallowed_asset_class_denies(write_mandate, sample_mandate_payload):
    sample_mandate_payload["universe"]["asset_classes"] = ["us_equity"]
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=100.0)
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_DENY
    assert d.breach is not None
    assert d.breach.kind == "universe"
    assert d.breach.limit == "asset_classes"


def test_daily_count_pauses_for_reauth(write_mandate, sample_mandate_payload):
    from bybit_mcp.safety.daily_count import increment_daily_count
    write_mandate("bybit", sample_mandate_payload)
    for _ in range(50):
        increment_daily_count("bybit")
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=100.0)
    d = g.check("bybit_place_order", {}, intent)
    print(f"\nDEBUG daily_count: decision={d.decision!r}, reason={d.reason!r}, breach={d.breach!r}")
    assert d.decision == DECISION_PAUSE
    assert d.breach is not None
    assert d.breach.limit == "max_trades_per_day"


def test_leverage_breach_pauses_for_reauth(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    # 4000 / 5000 = 0.8 leverage; sample max is 3 → passes
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=200.0)  # 200/5000 = 0.04 → ok
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW


def test_funding_ceiling_pauses_for_reauth(write_mandate, sample_mandate_payload):
    """A buy above the funding ceiling (defense-in-depth) pauses for re-auth.

    Use the isolated ``check()`` exposure math: the order's effective exposure
    equals its notional (no portfolio aggregation). Order notional = 4800
    (under notional cap 1000? — no, still over). So we need to bump the cap to
    allow the notional-cap to pass and only the funding check to trip. Set the
    notional cap to 6000 so the test exercises the funding ceiling.
    """
    sample_mandate_payload["hard_caps"]["max_order_notional_usd"] = 6000.0
    sample_mandate_payload["hard_caps"]["max_total_exposure_usd"] = 9000.0
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=4800.0)  # 4800 / 5000 funding = 0.96 leverage ok
    # 4800 < notional cap 6000 → passes notional
    # 4800 < exposure cap 9000 → passes exposure
    # 4800/5000 = 0.96 < leverage cap 3.0 → passes leverage
    # 1 < 50 → passes daily
    # buy 4800 > 5000 funding → no (4800 < 5000) → passes funding
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW

    # Now test the actual funding breach: order 5500 > 5000 funding, notional cap raised
    sample_mandate_payload["hard_caps"]["max_order_notional_usd"] = 6000.0
    sample_mandate_payload["hard_caps"]["max_total_exposure_usd"] = 9000.0
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=5500.0)  # buy 5500 > 5000 funding → PAUSE
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_PAUSE
    assert d.breach is not None
    assert d.breach.limit == "account_funding_usd"


def test_happy_path_allows(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=100.0)
    d = g.check("bybit_place_order", {}, intent)
    assert d.decision == DECISION_ALLOW
    assert d.intent is not None
    assert d.intent.notional_usd == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# check_with_state (portfolio-aware exposure)
# ---------------------------------------------------------------------------


def test_check_with_state_over_exposure_pauses(write_mandate, sample_mandate_payload):
    write_mandate("bybit", sample_mandate_payload)
    g = MandateGate("bybit", session_id="s")
    intent = _ok_intent(notional=500.0)
    d = g.check_with_state("bybit_place_order", {}, intent, current_exposure_usd=4700.0)
    # 4700 + 500 = 5200 > 5000 → pause
    assert d.decision == DECISION_PAUSE
    assert d.breach is not None
    assert d.breach.limit == "max_total_exposure_usd"
