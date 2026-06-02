"""Bybit v5 enum constants — match the Go SDK's v5_enum.go for parity."""

from __future__ import annotations

from enum import Enum


class CategoryV5(str, Enum):
    """Product category."""

    SPOT = "spot"
    LINEAR = "linear"
    INVERSE = "inverse"
    OPTION = "option"


class Side(str, Enum):
    BUY = "Buy"
    SELL = "Sell"


class OrderType(str, Enum):
    MARKET = "Market"
    LIMIT = "Limit"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"
    POST_ONLY = "PostOnly"


class TriggerBy(str, Enum):
    LAST = "LastPrice"
    INDEX = "IndexPrice"
    MARK = "MarkPrice"


class TpSlMode(str, Enum):
    FULL = "Full"
    PARTIAL = "Partial"


class PositionIdx(int, Enum):
    """Position index — required in hedge mode, 0=one-way mode."""

    ONE_WAY = 0
    HEDGE_LONG = 1
    HEDGE_SHORT = 2


class OrderFilter(str, Enum):
    ORDER = "Order"
    TP_SL_ORDER = "tpslOrder"
    STOP_ORDER = "StopOrder"


class SlippageToleranceType(str, Enum):
    TICK_SIZE = "TickSize"
    PERCENT = "Percent"


class AccountTypeV5(str, Enum):
    UNIFIED = "UNIFIED"
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class Interval(str, Enum):
    """Kline interval — 1..60 minute, 1..4 hour, 1D, 1W, 1M."""

    M1 = "1"
    M3 = "3"
    M5 = "5"
    M15 = "15"
    M30 = "30"
    H1 = "60"
    H2 = "120"
    H4 = "240"
    H6 = "360"
    H12 = "720"
    D1 = "D"
    W1 = "W"
    MO1 = "M"

    @property
    def label(self) -> str:
        """Human-friendly label (matches the standard timeframe string)."""
        mapping = {
            "1": "1m", "3": "3m", "5": "5m", "15": "15m", "30": "30m",
            "60": "1h", "120": "2h", "240": "4h", "360": "6h", "720": "12h",
            "D": "1d", "W": "1w", "M": "1M",
        }
        return mapping[self.value]


class MarginMode(str, Enum):
    ISOLATED = "ISOLATED"
    CROSS = "CROSSED"


# ----------------------------------------------------------------------------
# Vibe-Trading compatibility: market code normalisation
# ----------------------------------------------------------------------------


def to_bybit_symbol(code: str) -> str:
    """Convert Vibe-Trading ``BTC-USDT`` style to Bybit ``BTCUSDT``.

    Raises:
        ValueError: Empty / wrong-shape code.
    """
    if not code:
        raise ValueError("symbol must be non-empty")
    parts = code.upper().replace("_", "-").split("-")
    parts = [p for p in parts if p]
    if len(parts) == 2:
        return f"{parts[0]}{parts[1]}"
    if len(parts) == 1:
        return parts[0]
    raise ValueError(f"unsupported symbol format: {code!r}")


def from_bybit_symbol(symbol: str) -> str:
    """Convert Bybit ``BTCUSDT`` style to Vibe-Trading ``BTC-USDT``.

    Heuristic: split the token on the boundary between a base ticker and a
    quote of length 3-5 (USDT/USDC/USD/BTC/ETH).
    """
    if not symbol:
        return ""
    known_quotes = ("USDT", "USDC", "USD", "BTC", "ETH", "EUR")
    for q in known_quotes:
        if symbol.endswith(q) and len(symbol) > len(q):
            return f"{symbol[: -len(q)]}-{q}"
    return symbol
