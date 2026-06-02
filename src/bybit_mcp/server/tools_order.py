"""Order-placing tools (gated by :class:`MandateGate`).

Every tool here runs the 6-step fail-closed gate BEFORE any broker call.
On DENY / PAUSE_FOR_REAUTH the gate:

1. Writes one ``order_rejected`` / ``breach`` audit event to the shared ledger.
2. Returns a structured refusal envelope (mirrors Vibe-Trading's
   ``MCPRemoteTool._refusal`` shape) — the LLM never sees a non-error
   "no, you can't do that" without an attached audit record.

On ALLOW the gate calls the broker, then audits ``order_placed`` (or
``order_rejected`` on broker error). The daily counter is incremented only
on ALLOW + non-error broker response (a failed forward never placed an
order, so it never consumes a count — H2).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from fastmcp import FastMCP

from bybit_mcp.client.rest import BybitAPIError, BybitError, BybitTransportError
from bybit_mcp.safety.extractors import (
    extract_amend_order_intent,
    extract_place_order_intent,
)
from bybit_mcp.safety.guard import (
    DECISION_ALLOW,
    DECISION_DENY,
    build_refusal,
)
from bybit_mcp.safety.mandate import load_mandate
from bybit_mcp.server.state import get_client, make_gate

logger = logging.getLogger(__name__)


def _ok(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _err(exc: Exception, op: str) -> str:
    if isinstance(exc, BybitAPIError):
        return json.dumps(
            {"status": "error", "op": op, "retCode": exc.ret_code, "retMsg": exc.ret_msg},
            ensure_ascii=False,
        )
    if isinstance(exc, BybitTransportError):
        return json.dumps(
            {"status": "error", "op": op, "error": str(exc)}, ensure_ascii=False
        )
    return json.dumps({"status": "error", "op": op, "error": str(exc)}, ensure_ascii=False)


def _embed_live_action(forwarded: str, record: dict | None) -> str:
    """Embed the redacted audit record under the frozen live-action key (H5)."""
    if record is None:
        return forwarded
    try:
        payload = json.loads(forwarded)
    except (TypeError, ValueError):
        return forwarded
    if not isinstance(payload, dict):
        return forwarded
    payload["live_action"] = record
    return json.dumps(payload, ensure_ascii=False)


def _is_error_envelope(broker_response: dict | None) -> bool:
    if not isinstance(broker_response, dict):
        return True
    return str(broker_response.get("status", "")).lower() == "error"


def _gate_and_forward(
    *,
    remote_name: str,
    tool_args: dict[str, Any],
    intent_extractor: Callable[[dict[str, Any]], Any],
    forward: Callable[[], Any],
    session_id: str = "",
) -> str:
    """Run the gate, then forward on ALLOW, then audit + counter.

    Args:
        remote_name: The MCP tool name (e.g. ``bybit_place_order``).
        tool_args: Raw tool-call arguments.
        intent_extractor: The function that turns ``tool_args`` into an
            :class:`OrderIntent` (``extract_place_order_intent`` etc.).
        forward: Zero-arg callable that actually calls the broker.
        session_id: Originating session id, stamped on audit events.

    Returns:
        JSON string — either the forwarded broker result (ALLOW) or a
        structured refusal envelope (DENY / PAUSE).
    """
    gate = make_gate(session_id=session_id)
    intent = intent_extractor(tool_args)
    if intent is None:
        decision = gate.audit_decision_decision(
            kind="order_rejected",
            outcome="blocked",
            remote_name=remote_name,
            reason="order intent could not be parsed",
            checked=["mandate", "expiry", "halt_flag", "intent"],
            broker_request=tool_args,
        )
        return build_refusal(
            decision, broker=gate.broker, remote_tool=remote_name, record=None,
        )

    decision = gate.check(remote_name, tool_args, intent)
    if decision.decision != DECISION_ALLOW:
        mandate = load_mandate(gate.broker)
        record = gate.audit_decision(
            decision=decision,
            remote_name=remote_name,
            kind="order_rejected" if decision.decision == DECISION_DENY else "breach",
            outcome="blocked",
            broker_request=tool_args,
            broker_response=None,
            error=decision.reason,
            mandate=mandate,
        )
        return build_refusal(
            decision, broker=gate.broker, remote_tool=remote_name, record=record,
        )

    # ALLOW — forward to broker
    try:
        result = forward()
    except (BybitAPIError, BybitTransportError, BybitError) as exc:
        # The forward never placed an order (broker envelope error) — audit
        # ``order_rejected`` / ``error`` and DO NOT consume the daily count.
        mandate = load_mandate(gate.broker)
        record = gate.audit_decision(
            decision=decision,
            remote_name=remote_name,
            kind="order_rejected",
            outcome="error",
            broker_request=tool_args,
            broker_response={"status": "error", "error": str(exc)},
            error=str(exc),
            mandate=mandate,
        )
        return _err(exc, remote_name)

    # Successful forward — consume the daily count, audit ``order_placed``,
    # and embed the audit record under the frozen live-action key.
    gate.record_success()
    mandate = load_mandate(gate.broker)
    record = gate.audit_decision(
        decision=decision,
        remote_name=remote_name,
        kind="order_placed",
        outcome="accepted",
        broker_request=tool_args,
        broker_response=result if isinstance(result, dict) else {"raw": str(result)},
        error=None,
        mandate=mandate,
    )
    return _embed_live_action(_ok(result), record)


# Tiny extension to attach the decision helper to MandateGate (kept local to
# avoid leaking into the gate module).
def _attach_audit_decision_decision_helper() -> None:
    """Attach a small helper to :class:`MandateGate` for the pre-intent case."""
    from bybit_mcp.safety.guard import GateDecision, MandateGate

    def audit_decision_decision(
        self: "MandateGate",
        *,
        kind: str,
        outcome: str,
        remote_name: str,
        reason: str,
        checked: list[str],
        broker_request: dict | None = None,
    ) -> "GateDecision":
        decision = GateDecision(
            decision=DECISION_DENY,
            checked_limits=checked,
            reason=reason,
        )
        mandate = load_mandate(self.broker)
        self.audit_decision(
            decision=decision,
            remote_name=remote_name,
            kind=kind,  # type: ignore[arg-type]
            outcome=outcome,  # type: ignore[arg-type]
            broker_request=broker_request,
            broker_response=None,
            error=reason,
            mandate=mandate,
        )
        return decision

    if not hasattr(MandateGate, "audit_decision_decision"):
        MandateGate.audit_decision_decision = audit_decision_decision  # type: ignore[attr-defined]


_attach_audit_decision_decision_helper()


def register_order_tools(mcp: FastMCP) -> None:
    """Register all order write tools on the given FastMCP server."""

    @mcp.tool(
        name="bybit_place_order",
        description=(
            "Place a Bybit v5 order. GATED by the user-side mandate — DENY on "
            "missing/expired mandate, kill-switch trip, exclude-list hit, "
            "disallowed instrument, over-notional, over-exposure, over-leverage, "
            "or daily-cap breach. On ALLOW the order is forwarded; on broker "
            "error the daily count is NOT consumed. "
            "Returns a refusal envelope (status=blocked) on DENY/PAUSE."
        ),
    )
    async def bybit_place_order(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        side: str = "Buy",
        order_type: str = "Market",
        qty: str = "0.001",
        price: str | None = None,
        time_in_force: str | None = None,
        reduce_only: bool | None = None,
        order_link_id: str | None = None,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        position_idx: int | None = None,
        notional_usd: str | None = None,
    ) -> str:
        tool_args: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
        }
        if price is not None:
            tool_args["price"] = price
        if time_in_force is not None:
            tool_args["timeInForce"] = time_in_force
        if reduce_only is not None:
            tool_args["reduceOnly"] = reduce_only
        if order_link_id is not None:
            tool_args["orderLinkId"] = order_link_id
        if take_profit is not None:
            tool_args["takeProfit"] = take_profit
        if stop_loss is not None:
            tool_args["stopLoss"] = stop_loss
        if position_idx is not None:
            tool_args["positionIdx"] = position_idx
        if notional_usd is not None:
            tool_args["notional_usd"] = notional_usd

        async def _forward() -> dict[str, Any]:
            async with get_client() as client:
                return await client.create_order(
                    category=category, symbol=symbol, side=side, order_type=order_type,
                    qty=qty, price=price, time_in_force=time_in_force,
                    reduce_only=reduce_only, order_link_id=order_link_id,
                    take_profit=take_profit, stop_loss=stop_loss,
                    position_idx=position_idx,
                )

        return _gate_and_forward(
            remote_name="bybit_place_order",
            tool_args=tool_args,
            intent_extractor=extract_place_order_intent,
            forward=_forward,
        )

    @mcp.tool(
        name="bybit_amend_order",
        description=(
            "Amend a Bybit v5 order (price / qty / TP / SL). GATED by mandate. "
            "Note: an amend that increases notional is enforced on the LARGER "
            "of (new notional, new_qty × live price)."
        ),
    )
    async def bybit_amend_order(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        side: str = "Buy",
        order_id: str | None = None,
        order_link_id: str | None = None,
        qty: str | None = None,
        new_qty: str | None = None,
        price: str | None = None,
        take_profit: str | None = None,
        stop_loss: str | None = None,
    ) -> str:
        tool_args: dict[str, Any] = {
            "category": category, "symbol": symbol, "side": side,
        }
        if order_id:
            tool_args["orderId"] = order_id
        if order_link_id:
            tool_args["orderLinkId"] = order_link_id
        if qty is not None:
            tool_args["new_qty"] = qty  # normalize
        if new_qty is not None:
            tool_args["new_qty"] = new_qty
        if price is not None:
            tool_args["price"] = price
        if take_profit is not None:
            tool_args["takeProfit"] = take_profit
        if stop_loss is not None:
            tool_args["stopLoss"] = stop_loss

        async def _forward() -> dict[str, Any]:
            kwargs: dict[str, Any] = {
                "category": category, "symbol": symbol,
                "order_id": order_id, "order_link_id": order_link_id,
                "qty": qty or new_qty, "price": price,
                "take_profit": take_profit, "stop_loss": stop_loss,
            }
            async with get_client() as client:
                return await client.amend_order(**kwargs)

        return _gate_and_forward(
            remote_name="bybit_amend_order",
            tool_args=tool_args,
            intent_extractor=extract_amend_order_intent,
            forward=_forward,
        )

    @mcp.tool(
        name="bybit_cancel_order",
        description=(
            "Cancel a single Bybit v5 order by ``orderId`` or ``orderLinkId``. "
            "GATED by mandate (consumes a daily count on ALLOW)."
        ),
    )
    async def bybit_cancel_order(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        order_id: str | None = None,
        order_link_id: str | None = None,
    ) -> str:
        tool_args: dict[str, Any] = {
            "category": category, "symbol": symbol,
        }
        if order_id:
            tool_args["orderId"] = order_id
        if order_link_id:
            tool_args["orderLinkId"] = order_link_id

        async def _forward() -> dict[str, Any]:
            async with get_client() as client:
                return await client.cancel_order(
                    category=category, symbol=symbol,
                    order_id=order_id, order_link_id=order_link_id,
                )

        return _gate_and_forward(
            remote_name="bybit_cancel_order",
            tool_args=tool_args,
            intent_extractor=extract_place_order_intent,  # symbol+side only — cancel has no notional
            forward=_forward,
        )

    @mcp.tool(
        name="bybit_cancel_all_orders",
        description=(
            "Cancel all Bybit v5 open orders in a category (optionally filtered "
            "by symbol). GATED by mandate."
        ),
    )
    async def bybit_cancel_all_orders(
        category: str = "linear",
        symbol: str | None = None,
    ) -> str:
        tool_args: dict[str, Any] = {"category": category}
        if symbol:
            tool_args["symbol"] = symbol

        async def _forward() -> dict[str, Any]:
            async with get_client() as client:
                return await client.cancel_all_orders(category=category, symbol=symbol)

        return _gate_and_forward(
            remote_name="bybit_cancel_all_orders",
            tool_args=tool_args,
            intent_extractor=extract_place_order_intent,
            forward=_forward,
        )

    @mcp.tool(
        name="bybit_set_leverage",
        description=(
            "Set leverage for a Bybit v5 symbol (position-level). GATED by "
            "mandate (the post-set leverage must respect ``max_leverage``)."
        ),
    )
    async def bybit_set_leverage(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        leverage: int = 1,
    ) -> str:
        tool_args = {"category": category, "symbol": symbol, "leverage": int(leverage)}

        async def _forward() -> dict[str, Any]:
            async with get_client() as client:
                return await client.set_leverage(
                    category=category, symbol=symbol, leverage=int(leverage),
                )

        return _gate_and_forward(
            remote_name="bybit_set_leverage",
            tool_args=tool_args,
            intent_extractor=extract_place_order_intent,
            forward=_forward,
        )

    @mcp.tool(
        name="bybit_set_trading_stop",
        description=(
            "Attach / change TP / SL on an open Bybit v5 position. GATED by "
            "mandate. (Note: TP/SL price changes do not alter notional at the "
            "gate; the gate enforces the structural caps only.)"
        ),
    )
    async def bybit_set_trading_stop(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        position_idx: int = 0,
        take_profit: str | None = None,
        stop_loss: str | None = None,
        tpsl_mode: str | None = None,
    ) -> str:
        tool_args: dict[str, Any] = {
            "category": category, "symbol": symbol, "positionIdx": int(position_idx),
        }
        if take_profit is not None:
            tool_args["takeProfit"] = take_profit
        if stop_loss is not None:
            tool_args["stopLoss"] = stop_loss
        if tpsl_mode is not None:
            tool_args["tpslMode"] = tpsl_mode

        async def _forward() -> dict[str, Any]:
            async with get_client() as client:
                return await client.set_trading_stop(
                    category=category, symbol=symbol, position_idx=int(position_idx),
                    take_profit=take_profit, stop_loss=stop_loss, tpsl_mode=tpsl_mode,
                )

        return _gate_and_forward(
            remote_name="bybit_set_trading_stop",
            tool_args=tool_args,
            intent_extractor=extract_place_order_intent,
            forward=_forward,
        )
