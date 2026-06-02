"""Bybit order-intent extractors.

The mandate gate (``:mod:`bybit_mcp.safety.guard``) needs a normalized,
broker-agnostic :class:`OrderIntent` derived from the raw tool call. The
extractor is the ONLY place that knows the Bybit-specific field names (``qty``
/ ``price`` / ``category`` / ``symbol`` …) — the gate itself is broker-agnostic
and just compares the resulting intent against the mandate.

The normalization rules mirror the H3 / H4 enforcement notes from
Vibe-Trading's :func:`src.live.order_guard.LiveOrderGuardTool._normalize_intent_notional`:

* **H3** — if the call carries BOTH ``qty`` and ``notional_usd``, the gate
  enforces the LARGER of the two (deriving ``quantity`` × live price), so a
  small notional can't smuggle a huge quantity past the cap.
* **H4** — a quantity-only call derives its notional from a live quote so
  the notional cap stays enforceable.

The function is a pure translator: parse → normalize → return. It does NOT
hit the network (no quote fetch); the gate does that in step 6 with a
fail-closed policy of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bybit_mcp.client.enums import CategoryV5
from bybit_mcp.safety.mandate import AssetClass, InstrumentType


@dataclass(frozen=True)
class OrderIntent:
    """Broker-agnostic normalized order (matches Vibe-Trading's :class:`OrderIntent`).

    Attributes:
        symbol: Normalized upper-case symbol (e.g. ``BTCUSDT`` for Bybit).
        side: ``"buy"`` or ``"sell"``.
        notional_usd: Order notional in USD when derivable.
        quantity: Coin/contract quantity when notional is not given.
        instrument_type: :class:`InstrumentType` — bybit-mcp only supports
            ``CRYPTO`` (linear / inverse / spot all map to crypto).
        asset_class: Explicit universe :class:`AssetClass`. bybit-mcp defaults
            to :attr:`AssetClass.CRYPTO`.
        category: Bybit product category (linear/inverse/spot/option). Carried
            through for the actual broker call; not part of the gate math.
    """

    symbol: str
    side: str
    notional_usd: float | None
    quantity: float | None
    instrument_type: InstrumentType
    asset_class: AssetClass | None = None
    category: CategoryV5 = CategoryV5.LINEAR


def _side_to_str(side: str) -> str:
    """Bybit ``Buy`` / ``Sell`` → lower-case ``buy`` / ``sell`` for the gate."""
    s = (side or "").strip().lower()
    if s in {"buy", "sell"}:
        return s
    return s


def extract_place_order_intent(tool_args: dict[str, Any]) -> OrderIntent | None:
    """Extract a normalized :class:`OrderIntent` from a Bybit ``place_order`` call.

    Args:
        tool_args: The raw tool call arguments, e.g.::

            {
                "category": "linear",
                "symbol": "BTCUSDT",
                "side": "Buy",
                "orderType": "Market",
                "qty": "0.001",
                "price": "65000",  # optional
                "notional_usd": "65.0",  # optional, optional vs qty enforcement
                "timeInForce": "GTC",
                "reduceOnly": false,
            }

    Returns:
        The normalized :class:`OrderIntent`, or ``None`` when the call is
        unparseable (→ gate fail-closes).
    """
    symbol = str(tool_args.get("symbol", "")).strip().upper()
    side = _side_to_str(str(tool_args.get("side", "")))
    if not symbol or side not in {"buy", "sell"}:
        return None

    qty_raw = tool_args.get("qty") or tool_args.get("quantity")
    quantity = _opt_float(qty_raw)
    notional = _opt_float(tool_args.get("notional_usd"))

    if quantity is not None and quantity <= 0:
        return None
    if notional is not None and notional <= 0:
        return None

    category_str = str(tool_args.get("category", "linear")).lower()
    try:
        category = CategoryV5(category_str)
    except ValueError:
        category = CategoryV5.LINEAR

    return OrderIntent(
        symbol=symbol,
        side=side,
        notional_usd=notional,
        quantity=quantity,
        instrument_type=InstrumentType.CRYPTO,
        asset_class=AssetClass.CRYPTO,
        category=category,
    )


def extract_amend_order_intent(tool_args: dict[str, Any]) -> OrderIntent | None:
    """Extract an :class:`OrderIntent` for an amend call (qty / price change).

    Amend does not change side / category / symbol, so the intent is built from
    the embedded ``new_qty`` / ``new_notional`` fields (if any) plus the symbol.
    Used by the gate ONLY when the amend would change the order's effective
    notional (e.g. an upsize). An amend that only changes price on a limit
    order has the same notional → gate pass-through with no math change.
    """
    symbol = str(tool_args.get("symbol", "")).strip().upper()
    if not symbol:
        return None

    side_raw = str(tool_args.get("side", "")).strip().lower()
    if side_raw not in {"buy", "sell"}:
        # Without an explicit side, amend is treated as a neutral modification
        # that the gate cannot quantify → fail-closed (return None → gate
        # returns an "intent unparseable" DENY).
        return None

    quantity = _opt_float(tool_args.get("new_qty") or tool_args.get("qty"))
    notional = _opt_float(tool_args.get("new_notional") or tool_args.get("notional_usd"))

    if quantity is not None and quantity <= 0:
        return None
    if notional is not None and notional <= 0:
        return None

    category_str = str(tool_args.get("category", "linear")).lower()
    try:
        category = CategoryV5(category_str)
    except ValueError:
        category = CategoryV5.LINEAR

    return OrderIntent(
        symbol=symbol,
        side=side_raw,
        notional_usd=notional,
        quantity=quantity,
        instrument_type=InstrumentType.CRYPTO,
        asset_class=AssetClass.CRYPTO,
        category=category,
    )


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out
