"""The 6-step fail-closed mandate gate for the bybit-mcp server.

This is a standalone, broker-agnostic port of Vibe-Trading's
``src.live.order_guard.LiveOrderGuardTool`` so the bybit-mcp process can
enforce the same mandate contract WITHOUT importing Vibe-Trading at runtime.
The behaviour, decision verbs, and audit record shape are intentionally
identical so a single mandate file / audit ledger serves both the in-repo
guard and the bybit-mcp guard.

Pipeline (every step fail-closed; first failure short-circuits):

1. ``load_mandate`` — no valid mandate / unknown schema version → DENY.
2. ``expires_at`` — past the user-set expiry → DENY (PAUSE_FOR_REAUTH).
3. ``halt_flag_set`` — kill switch tripped → DENY, no remote call.
4. ``extract_order_intent`` — unparseable order args → DENY.
5. ``quantity → notional`` — quantity-only orders derive notional from the
   broker's read quote (fail-closed if no quote is obtainable).
6. ``check_mandate`` — quantitative + structural caps / universe / asset
   class / daily count / funding ceiling (defense-in-depth).

The daily ``trade_counter.json`` is incremented only on a confirmed ALLOW with
a non-error broker result. Every decision writes one redacted live-action
audit event to the shared ledger.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from bybit_mcp.safety.audit import (
    LiveActionEvent,
    LiveActionKind,
    LiveActionOutcome,
    write_live_action,
)
from bybit_mcp.safety.daily_count import increment_daily_count, read_daily_count
from bybit_mcp.safety.extractors import OrderIntent
from bybit_mcp.safety.halt import halt_flag_set
from bybit_mcp.safety.mandate import (
    MANDATE_SCHEMA_VERSION,
    Mandate,
    load_mandate,
)

logger = logging.getLogger(__name__)

DECISION_ALLOW = "allow"
DECISION_DENY = "deny"
DECISION_PAUSE = "pause_for_reauth"

LIVE_ACTION_RESULT_KEY = "live_action"

CHECKED_LIMITS = [
    "mandate", "expiry", "halt_flag", "intent",
    "exclude_symbols", "allowed_instruments", "asset_classes",
    "max_order_notional_usd", "max_total_exposure_usd",
    "max_leverage", "max_trades_per_day", "account_funding_usd",
]


# ---------------------------------------------------------------------------
# Decision / breach types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BreachEvent:
    """Breach produced by the gate (mirrors Vibe-Trading's ``BreachEvent``)."""

    limit: str
    limit_value: float
    attempted_value: float
    kind: str  # "universe" | "instrument" | "quantitative"
    overage: float = 0.0
    detail: str = ""


@dataclass(frozen=True)
class GateDecision:
    """Result of a single gate evaluation."""

    decision: str  # "allow" | "deny" | "pause_for_reauth"
    checked_limits: list[str] = field(default_factory=list)
    reason: str = ""
    breach: Optional[BreachEvent] = None
    intent: Optional[OrderIntent] = None


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


class MandateGate:
    """Fail-closed 6-step mandate gate for the bybit-mcp server.

    Construct once per MCP tool invocation (cheap; the mandate/halt/counter
    are re-read from disk every call so a user-side commit / trip is
    immediately visible to the next order attempt).
    """

    def __init__(
        self,
        broker: str,
        session_id: str = "",
        *,
        quote_lookup: Optional[callable] = None,  # type: ignore[valid-type]
    ) -> None:
        self.broker = broker.strip().lower()
        self.session_id = session_id
        # quote_lookup(symbol, category) -> Optional[float]
        # If None, quantity-only orders are fail-closed at step 5.
        self._quote_lookup = quote_lookup

    # -- public API --------------------------------------------------------

    def check(
        self,
        remote_name: str,
        tool_args: dict[str, Any],
        intent: OrderIntent,
    ) -> GateDecision:
        """Run steps 1-6 and return the gate decision (never raises)."""
        if not self.broker:
            return GateDecision(
                decision=DECISION_DENY,
                checked_limits=["mandate"],
                reason="broker key is empty",
            )

        mandate = load_mandate(self.broker)
        if mandate is None or mandate.schema_version != MANDATE_SCHEMA_VERSION:
            return self._deny_pre_intent(
                reason="no valid mandate on file",
                checked=["mandate"],
                mandate=None,
            )

        if self._is_expired(mandate):
            return self._deny_pre_intent(
                reason="mandate expired — re-authorize",
                checked=["mandate", "expiry"],
                mandate=mandate,
                reauth=True,
            )

        if halt_flag_set(self.broker):
            return self._deny_pre_intent(
                reason="live trading halted",
                checked=["mandate", "expiry", "halt_flag"],
                mandate=mandate,
            )

        # Step 4 already produced `intent` (the extractor ran in the tool
        # wrapper). The gate is responsible for step 5: derive notional from
        # quantity when needed.
        priced = self._normalize_intent_notional(intent)
        if priced is None:
            return self._deny_pre_intent(
                reason="quantity order notional could not be priced (fail-closed)",
                checked=["mandate", "expiry", "halt_flag", "intent", "quote"],
                mandate=mandate,
            )

        # Step 6: pure decision function over the priced intent.
        daily_count = read_daily_count(self.broker)
        breach = self._check_mandate(mandate, priced, daily_count=daily_count)
        if breach is None:
            return GateDecision(
                decision=DECISION_ALLOW,
                checked_limits=list(CHECKED_LIMITS),
                intent=priced,
            )

        if breach.kind in ("universe", "instrument"):
            return GateDecision(
                decision=DECISION_DENY,
                checked_limits=list(CHECKED_LIMITS),
                reason=breach.detail or f"order breaches {breach.limit}",
                breach=breach,
                intent=priced,
            )
        # quantitative → pause for re-auth
        return GateDecision(
            decision=DECISION_PAUSE,
            checked_limits=list(CHECKED_LIMITS),
            reason=breach.detail or f"order breaches {breach.limit}",
            breach=breach,
            intent=priced,
        )

    # -- intent normalization ---------------------------------------------

    def _normalize_intent_notional(self, intent: OrderIntent) -> OrderIntent | None:
        """Stamp a single authoritative ``notional_usd`` onto the intent.

        Closes the H3 / H4 bypasses from Vibe-Trading's SPEC §4:

        * H3 — an order carrying BOTH ``notional_usd`` and ``quantity`` is
          enforced on the LARGER of (explicit notional, ``quantity`` × live
          price), so a small notional can't smuggle a huge quantity past the
          cap.
        * H4 — a quantity-only order derives its notional from a live quote so
          the notional cap stays enforceable.

        Fail-closed: when ``quantity`` is present but NO quote can be obtained,
        the order is DENIED (returns ``None``).
        """
        if intent.quantity is None:
            return intent

        price = self._quote_price(intent)
        if price is None:
            return None
        implied = intent.quantity * price
        if implied != implied or implied <= 0:  # NaN / non-positive → fail-closed
            return None

        explicit = intent.notional_usd if intent.notional_usd is not None else 0.0
        enforced = max(float(explicit), implied)
        return OrderIntent(
            symbol=intent.symbol,
            side=intent.side,
            notional_usd=enforced,
            quantity=intent.quantity,
            instrument_type=intent.instrument_type,
            asset_class=intent.asset_class,
            category=intent.category,
        )

    def _quote_price(self, intent: OrderIntent) -> Optional[float]:
        if self._quote_lookup is None:
            return None
        try:
            price = self._quote_lookup(intent.symbol, intent.category.value)
        except Exception as exc:  # noqa: BLE001
            logger.warning("quote lookup failed for %s: %s", intent.symbol, exc)
            return None
        if price is None:
            return None
        try:
            value = float(price)
        except (TypeError, ValueError):
            return None
        if value != value or value <= 0:  # NaN / non-positive
            return None
        return value

    # -- check_mandate (broker-agnostic) -----------------------------------

    def _check_mandate(
        self,
        mandate: Mandate,
        intent: OrderIntent,
        *,
        daily_count: int,
    ) -> Optional[BreachEvent]:
        """Evaluate one priced intent against the mandate (fail-closed)."""
        caps = mandate.hard_caps
        universe = mandate.universe

        symbol = (intent.symbol or "").strip().upper()
        if not symbol or intent.side not in ("buy", "sell"):
            return BreachEvent(
                limit="order_intent", limit_value=0.0, attempted_value=0.0,
                kind="instrument", detail="order intent missing symbol or side",
            )

        # 1. Exclude-list
        if symbol in {s.strip().upper() for s in universe.exclude_symbols}:
            return BreachEvent(
                limit="exclude_symbols", limit_value=0.0, attempted_value=0.0,
                kind="universe", detail=f"{symbol} is on the mandate exclude list",
            )

        # 2. Instrument-type allowance
        if intent.instrument_type not in caps.allowed_instruments:
            return BreachEvent(
                limit="allowed_instruments", limit_value=0.0, attempted_value=0.0,
                kind="instrument",
                detail=f"{intent.instrument_type.value} not in allowed_instruments",
            )

        # 3. Asset-class allowance
        asset_class = intent.asset_class
        if asset_class is not None and asset_class not in universe.asset_classes:
            return BreachEvent(
                limit="asset_classes", limit_value=0.0, attempted_value=0.0,
                kind="universe",
                detail=f"{asset_class.value} not in permitted asset_classes",
            )

        # 4. Single-order notional
        notional = intent.notional_usd
        if notional is None or notional <= 0:
            return BreachEvent(
                limit="order_intent", limit_value=0.0, attempted_value=0.0,
                kind="instrument", detail="order notional could not be resolved",
            )
        if notional > caps.max_order_notional_usd:
            return BreachEvent(
                limit="max_order_notional_usd",
                limit_value=caps.max_order_notional_usd,
                attempted_value=notional,
                overage=notional - caps.max_order_notional_usd,
                kind="quantitative",
            )

        # 5. Total exposure — bybit-mcp has no observable positions history
        #    on the read path the same way the in-repo guard has. We treat
        #    post-trade exposure as the order notional itself for a single
        #    isolated live order; a portfolio-aware downstream caller can
        #    pass a pre-aggregated ``current_exposure`` via
        #    :meth:`check_with_state` for richer math.
        attempted_exposure = float(notional)
        if attempted_exposure > caps.max_total_exposure_usd:
            return BreachEvent(
                limit="max_total_exposure_usd",
                limit_value=caps.max_total_exposure_usd,
                attempted_value=attempted_exposure,
                overage=attempted_exposure - caps.max_total_exposure_usd,
                kind="quantitative",
            )

        # 6. Gross leverage
        if caps.account_funding_usd <= 0:
            return BreachEvent(
                limit="max_leverage",
                limit_value=caps.max_leverage,
                attempted_value=float("inf"),
                overage=float("inf"),
                kind="quantitative",
                detail="account_funding_usd is non-positive (fail-closed)",
            )
        post_leverage = attempted_exposure / caps.account_funding_usd
        if post_leverage > caps.max_leverage:
            return BreachEvent(
                limit="max_leverage",
                limit_value=caps.max_leverage,
                attempted_value=post_leverage,
                overage=post_leverage - caps.max_leverage,
                kind="quantitative",
            )

        # 7. Daily count
        attempted_count = daily_count + 1
        if attempted_count > caps.max_trades_per_day:
            return BreachEvent(
                limit="max_trades_per_day",
                limit_value=float(caps.max_trades_per_day),
                attempted_value=float(attempted_count),
                overage=float(attempted_count - caps.max_trades_per_day),
                kind="quantitative",
            )

        # 8. Funding ceiling (defense-in-depth; broker is the real ceiling)
        if intent.side == "buy" and attempted_exposure > caps.account_funding_usd:
            return BreachEvent(
                limit="account_funding_usd",
                limit_value=caps.account_funding_usd,
                attempted_value=attempted_exposure,
                overage=attempted_exposure - caps.account_funding_usd,
                kind="quantitative",
                detail="post-trade exposure exceeds mirrored funding ceiling",
            )

        return None

    def check_with_state(
        self,
        remote_name: str,
        tool_args: dict[str, Any],
        intent: OrderIntent,
        *,
        current_exposure_usd: float | None = None,
        positions_market_value: float | None = None,
    ) -> GateDecision:
        """Variant of :meth:`check` that accepts an external exposure snapshot.

        Use this when the caller has already fetched live positions/balance
        from the broker's read path and wants the gate to do a portfolio-aware
        exposure / leverage computation rather than treating the order
        notional as the only exposure.

        Args:
            remote_name: Broker tool name (audit only).
            tool_args: Raw tool args (audit only).
            intent: Pre-extracted intent (from ``extractors``).
            current_exposure_usd: Pre-trade total exposure in USD. ``None``
                (default) = treat the order notional as the only exposure.
            positions_market_value: Same as ``current_exposure_usd``; both
                names supported for call-site flexibility.

        Returns:
            The :class:`GateDecision`.
        """
        if current_exposure_usd is None and positions_market_value is None:
            return self.check(remote_name, tool_args, intent)
        base = self.check(remote_name, tool_args, intent)
        if base.decision != DECISION_ALLOW or base.intent is None:
            return base
        if base.intent.notional_usd is None:
            return base

        caps = load_mandate(self.broker).hard_caps  # type: ignore[union-attr]
        exposure = current_exposure_usd if current_exposure_usd is not None else positions_market_value  # type: ignore[assignment]
        signed = base.intent.notional_usd if base.intent.side == "buy" else -base.intent.notional_usd
        post_exposure = float(exposure) + signed  # type: ignore[operator]
        if post_exposure > caps.max_total_exposure_usd:
            breach = BreachEvent(
                limit="max_total_exposure_usd",
                limit_value=caps.max_total_exposure_usd,
                attempted_value=post_exposure,
                overage=post_exposure - caps.max_total_exposure_usd,
                kind="quantitative",
            )
            return GateDecision(
                decision=DECISION_PAUSE,
                checked_limits=list(CHECKED_LIMITS),
                reason=f"order breaches {breach.limit}",
                breach=breach,
                intent=base.intent,
            )
        return base

    # -- audit / decision helpers ------------------------------------------

    def audit_decision(
        self,
        *,
        decision: GateDecision,
        remote_name: str,
        kind: LiveActionKind,
        outcome: LiveActionOutcome,
        broker_request: dict[str, Any] | None = None,
        broker_response: dict[str, Any] | None = None,
        error: str | None = None,
        mandate: Mandate | None = None,
    ) -> dict[str, Any] | None:
        """Write one live-action audit event for the given decision.

        Auditing must never block a decision, so a write failure is logged
        and ``None`` is returned.

        Returns:
            The redacted audit record (the same dict written to the ledger),
            or ``None`` when the write failed.
        """
        try:
            event = LiveActionEvent(
                kind=kind,
                session_id=self.session_id,
                outcome=outcome,
                server=self.broker,
                remote_tool=remote_name,
                intent_normalized=_describe_intent(decision.intent),
                mandate_snapshot_ref=mandate.consent.consent_token_sha256 if mandate else None,
                consent_record_ref=mandate.consent.account_ref if mandate else None,
                broker_request=broker_request,
                broker_response=broker_response,
                gate_decision={
                    "allowed": decision.decision == DECISION_ALLOW,
                    "decision": decision.decision,
                    "checked_limits": list(decision.checked_limits),
                    **(
                        {
                            "limit": decision.breach.limit,
                            "kind": decision.breach.kind,
                            "limit_value": decision.breach.limit_value,
                            "attempted_value": decision.breach.attempted_value,
                        }
                        if decision.breach is not None
                        else {}
                    ),
                },
                error=error,
            )
            return write_live_action(event)
        except Exception as exc:  # noqa: BLE001 — auditing must never block
            logger.warning("bybit-mcp audit write failed (%s): %s", kind, exc)
            return None

    def record_success(self) -> None:
        """Increment the per-broker daily counter (call only on ALLOW + non-error)."""
        increment_daily_count(self.broker)

    def _deny_pre_intent(
        self,
        *,
        reason: str,
        checked: list[str],
        mandate: Mandate | None,
        reauth: bool = False,
    ) -> GateDecision:
        return GateDecision(
            decision=(DECISION_PAUSE if reauth else DECISION_DENY),
            checked_limits=checked,
            reason=reason,
        )

    def _is_expired(self, mandate: Mandate) -> bool:
        """Return whether the mandate is past its ``expires_at`` (fail-closed)."""
        raw = mandate.consent.expires_at
        try:
            expires = datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires


def _describe_intent(intent: OrderIntent | None) -> str | None:
    if intent is None:
        return None
    size = (
        f"${intent.notional_usd:g}"
        if intent.notional_usd is not None
        else f"{intent.quantity:g} units"
        if intent.quantity is not None
        else "?"
    )
    return f"{intent.side} {size} {intent.symbol} ({intent.category.value})"


# ---------------------------------------------------------------------------
# Refusal envelope (matches Vibe-Trading's MCPRemoteTool._refusal shape)
# ---------------------------------------------------------------------------


def build_refusal(
    decision: GateDecision,
    *,
    broker: str,
    remote_tool: str,
    record: dict[str, Any] | None = None,
) -> str:
    """Build the structured refusal envelope returned to the agent loop.

    Mirrors the ``MCPRemoteTool._refusal`` JSON shape so Vibe-Trading's SSE
    relay can read the redacted record under :data:`LIVE_ACTION_RESULT_KEY`
    and emit a ``live.action`` event without touching the agent loop.
    """
    reauth = decision.decision == DECISION_PAUSE
    payload: dict[str, Any] = {
        "status": "blocked",
        "decision": decision.decision,
        "reason": decision.reason,
        "broker": broker,
        "remote_tool": remote_tool,
        "requires_reauthorization": reauth,
    }
    if record is not None:
        payload[LIVE_ACTION_RESULT_KEY] = record
    if decision.breach is not None:
        payload["breach"] = {
            "limit": decision.breach.limit,
            "limit_value": decision.breach.limit_value,
            "attempted_value": decision.breach.attempted_value,
            "overage": decision.breach.overage,
            "kind": decision.breach.kind,
            "detail": decision.breach.detail,
        }
    return json.dumps(payload, ensure_ascii=False)
