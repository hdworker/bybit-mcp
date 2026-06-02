"""Pydantic response models for Bybit v5.

Kept lean: the MCP server only needs the fields it actually surfaces. The
Bybit v5 envelope is::

    {
        "retCode": 0,
        "retMsg": "OK",
        "result": { ... },
        "retExtInfo": {},
        "time": 1672324966009
    }

``retCode != 0`` is raised as :class:`BybitAPIError` by the client.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class BybitResponse(BaseModel):
    """Common envelope. ``retCode=0`` == success."""

    model_config = ConfigDict(extra="allow")

    retCode: int
    retMsg: str
    result: Any = None
    retExtInfo: dict[str, Any] = Field(default_factory=dict)
    time: int = 0


# ---- Market / public ---------------------------------------------------------


class TickerItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    lastPrice: Optional[str] = None
    indexPrice: Optional[str] = None
    markPrice: Optional[str] = None
    prevPrice24h: Optional[str] = None
    price24hPcnt: Optional[str] = None
    highPrice24h: Optional[str] = None
    lowPrice24h: Optional[str] = None
    volume24h: Optional[str] = None
    turnover24h: Optional[str] = None
    openInterest: Optional[str] = None
    fundingRate: Optional[str] = None
    nextFundingTime: Optional[str] = None
    bid1Price: Optional[str] = None
    ask1Price: Optional[str] = None


class OrderbookLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    price: str
    size: str


class OrderbookData(BaseModel):
    model_config = ConfigDict(extra="allow")

    s: str
    b: list[list[str]] = Field(default_factory=list)  # bids [[price, size], ...]
    a: list[list[str]] = Field(default_factory=list)  # asks
    ts: int
    u: int


class KlineItem(BaseModel):
    """One kline candle. Bybit returns ``[start_ms, open, high, low, close, volume, turnover]``."""

    start_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float

    @classmethod
    def from_raw(cls, raw: list[str | int | float]) -> "KlineItem":
        if len(raw) != 7:
            raise ValueError(f"kline item must have 7 fields, got {len(raw)}")
        return cls(
            start_ms=int(raw[0]),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            turnover=float(raw[6]),
        )


class FundingRateItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    fundingRate: str
    fundingRateTimestamp: str


class OpenInterestItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    openInterest: str
    timestamp: str


# ---- Account / private -------------------------------------------------------


class CoinBalance(BaseModel):
    model_config = ConfigDict(extra="allow")

    coin: str
    equity: Optional[str] = None
    usdValue: Optional[str] = None
    walletBalance: Optional[str] = None
    free: Optional[str] = None
    locked: Optional[str] = None
    unrealisedPnl: Optional[str] = None
    cumRealisedPnl: Optional[str] = None
    availableToWithdraw: Optional[str] = None


class WalletBalanceAccount(BaseModel):
    model_config = ConfigDict(extra="allow")

    accountType: str
    totalEquity: Optional[str] = None
    totalWalletBalance: Optional[str] = None
    totalAvailableBalance: Optional[str] = None
    totalPerpUPL: Optional[str] = None
    totalInitialMargin: Optional[str] = None
    totalMaintenanceMargin: Optional[str] = None
    coin: list[CoinBalance] = Field(default_factory=list)


class PositionItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    side: Optional[str] = None
    size: Optional[str] = None
    avgPrice: Optional[str] = None
    markPrice: Optional[str] = None
    liqPrice: Optional[str] = None
    leverage: Optional[str] = None
    positionValue: Optional[str] = None
    unrealisedPnl: Optional[str] = None
    cumRealisedPnl: Optional[str] = None
    takeProfit: Optional[str] = None
    stopLoss: Optional[str] = None
    positionIM: Optional[str] = None
    positionMM: Optional[str] = None
    positionIdx: int = 0
    createdTime: Optional[str] = None
    updatedTime: Optional[str] = None


# ---- Order writes ------------------------------------------------------------


class OrderCreateResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    orderId: str
    orderLinkId: str = ""


class OrderListItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    orderId: str
    orderLinkId: str = ""
    symbol: str
    side: Optional[str] = None
    orderType: Optional[str] = None
    price: Optional[str] = None
    qty: Optional[str] = None
    avgPrice: Optional[str] = None
    cumExecQty: Optional[str] = None
    cumExecValue: Optional[str] = None
    cumExecFee: Optional[str] = None
    orderStatus: Optional[str] = None
    timeInForce: Optional[str] = None
    reduceOnly: Optional[bool] = None
    createdTime: Optional[str] = None
    updatedTime: Optional[str] = None
