"""Mandate data model + loader for the bybit-mcp server.

Mirrors Vibe-Trading's ``src.live.mandate.model`` / ``src.live.mandate.store``
EXACTLY (same field names, same schema_version, same enums, same fail-closed
loader) so a mandate file committed by the Vibe-Trading consent UX is
readable by the bybit-mcp server without translation, and vice versa.

The mandate is the immutable bounded-autonomy contract: hard caps (notional /
exposure / leverage / daily count / allowed instruments), universe constraints
(asset-class buckets, market-cap / liquidity floors, exclude-list), and
consent metadata (provenance: who committed, when, when it expires).

The loader is fail-closed: a missing file, malformed JSON, or structurally
invalid record yields ``None`` so the enforcement gate DENIES all orders
rather than guessing at an unrecognized contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from bybit_mcp.safety.paths import broker_dir

logger = logging.getLogger(__name__)

MANDATE_SCHEMA_VERSION = 1
_MANDATE_FILENAME = "mandate.json"


class InstrumentType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    OPTION = "option"
    CRYPTO = "crypto"


class AssetClass(str, Enum):
    US_EQUITY = "us_equity"
    US_ETF = "us_etf"
    HK_EQUITY = "hk_equity"
    CN_EQUITY = "cn_equity"
    CRYPTO = "crypto"


@dataclass(frozen=True)
class HardCaps:
    """Layer (a): user-set quantitative ceilings."""

    account_funding_usd: float
    max_order_notional_usd: float
    max_total_exposure_usd: float
    max_leverage: float
    allowed_instruments: tuple[InstrumentType, ...]
    max_trades_per_day: int


@dataclass(frozen=True)
class UniverseConstraint:
    """Layer (b): user-set universe the agent picks symbols WITHIN."""

    asset_classes: tuple[AssetClass, ...]
    min_market_cap_usd: float | None
    min_avg_daily_volume_usd: float | None
    exclude_symbols: tuple[str, ...]


@dataclass(frozen=True)
class ConsentMeta:
    """Provenance proving the user (not the agent) authored this mandate."""

    created_at: str
    consent_token_sha256: str
    broker: str
    account_ref: str
    expires_at: str


@dataclass(frozen=True)
class Mandate:
    """Immutable bounded-autonomy mandate for one live broker channel."""

    schema_version: int
    hard_caps: HardCaps
    universe: UniverseConstraint
    consent: ConsentMeta
    flatten_on_halt: bool = False


def load_mandate(broker: str) -> Mandate | None:
    """Load the committed mandate for ``broker`` from the protected store.

    Reads ``<runtime_root>/live/<broker>/mandate.json``. Strict + fail-closed:
    missing / unreadable / malformed / structurally invalid → ``None``.
    ``expires_at`` and ``schema_version`` are carried through verbatim for the
    gate to evaluate.

    Args:
        broker: Broker key, e.g. ``"bybit"`` (lowercased + stripped).

    Returns:
        The committed :class:`Mandate`, or ``None``.
    """
    path = broker_dir(broker) / _MANDATE_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("bybit-mcp mandate for %s is unreadable/invalid JSON: %s", broker, exc)
        return None
    try:
        return _parse_mandate(raw)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("bybit-mcp mandate for %s failed structural validation: %s", broker, exc)
        return None


def _parse_mandate(raw: object) -> Mandate:
    if not isinstance(raw, dict):
        raise TypeError("mandate root must be a JSON object")
    caps = _require_dict(raw["hard_caps"], "hard_caps")
    universe = _require_dict(raw["universe"], "universe")
    consent = _require_dict(raw["consent"], "consent")

    hard_caps = HardCaps(
        account_funding_usd=float(caps["account_funding_usd"]),
        max_order_notional_usd=float(caps["max_order_notional_usd"]),
        max_total_exposure_usd=float(caps["max_total_exposure_usd"]),
        max_leverage=float(caps["max_leverage"]),
        allowed_instruments=tuple(InstrumentType(v) for v in caps["allowed_instruments"]),
        max_trades_per_day=int(caps["max_trades_per_day"]),
    )
    universe_constraint = UniverseConstraint(
        asset_classes=tuple(AssetClass(v) for v in universe["asset_classes"]),
        min_market_cap_usd=_opt_float(universe["min_market_cap_usd"]),
        min_avg_daily_volume_usd=_opt_float(universe["min_avg_daily_volume_usd"]),
        exclude_symbols=tuple(str(v) for v in universe["exclude_symbols"]),
    )
    consent_meta = ConsentMeta(
        created_at=str(consent["created_at"]),
        consent_token_sha256=str(consent["consent_token_sha256"]),
        broker=str(consent["broker"]),
        account_ref=str(consent["account_ref"]),
        expires_at=str(consent["expires_at"]),
    )
    return Mandate(
        schema_version=int(raw["schema_version"]),
        hard_caps=hard_caps,
        universe=universe_constraint,
        consent=consent_meta,
        flatten_on_halt=bool(raw.get("flatten_on_halt", False)),
    )


def _require_dict(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"mandate field {field!r} must be a JSON object")
    return value


def _opt_float(value: object) -> float | None:
    return None if value is None else float(value)
