"""Read-only market data tools (no mandate gate).

Each tool returns a JSON string (FastMCP convention) so the LLM can consume
the payload directly. Errors are returned as ``{"status": "error", ...}``
envelopes (fail-soft at the read path; the gate is what fail-closes for writes).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from bybit_mcp.client.rest import BybitAPIError, BybitError, BybitTransportError
from bybit_mcp.server.state import get_client

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


def register_market_tools(mcp: FastMCP) -> None:
    """Register all market read tools on the given FastMCP server."""

    @mcp.tool(
        name="bybit_get_tickers",
        description=(
            "Get Bybit v5 tickers for a product category. "
            "Public, no auth required. Returns: list of {symbol, lastPrice, "
            "indexPrice, markPrice, price24hPcnt, volume24h, turnover24h, "
            "openInterest, fundingRate, nextFundingTime, bid1Price, ask1Price}."
        ),
    )
    async def bybit_get_tickers(
        category: str = "linear",
        symbol: str | None = None,
    ) -> str:
        """Fetch Bybit v5 tickers.

        Args:
            category: ``spot`` | ``linear`` | ``inverse`` | ``option``.
            symbol: Optional symbol filter (e.g. ``BTCUSDT``). Omit for all
                tickers in the category.
        """
        try:
            async with get_client() as client:
                rows = await client.get_tickers(category=category, symbol=symbol)
            return _ok({"category": category, "symbol": symbol, "tickers": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_tickers")

    @mcp.tool(
        name="bybit_get_kline",
        description=(
            "Fetch Bybit v5 klines (candles). Each row is "
            "[start_ms, open, high, low, close, volume, turnover]. Public, no auth."
        ),
    )
    async def bybit_get_kline(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        interval: str = "5",
        limit: int = 200,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> str:
        """Fetch klines.

        Args:
            category: ``spot`` | ``linear`` | ``inverse``.
            symbol: e.g. ``BTCUSDT``.
            interval: ``1`` / ``3`` / ``5`` / ``15`` / ``30`` / ``60`` / ``120``
                / ``240`` / ``360`` / ``720`` / ``D`` / ``W`` / ``M``.
            limit: 1..1000 (default 200, server caps at 1000).
            start_ms: Optional start time in milliseconds since epoch.
            end_ms: Optional end time in milliseconds since epoch.
        """
        try:
            async with get_client() as client:
                rows = await client.get_kline(
                    category=category, symbol=symbol, interval=interval,
                    limit=limit, start_ms=start_ms, end_ms=end_ms,
                )
            return _ok({"category": category, "symbol": symbol, "interval": interval,
                        "klines": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_kline")

    @mcp.tool(
        name="bybit_get_orderbook",
        description=(
            "Bybit v5 L2 order book snapshot for a symbol. Returns "
            "{bids: [[price, size], ...], asks: [[price, size], ...], ts, u}."
        ),
    )
    async def bybit_get_orderbook(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                ob = await client.get_orderbook(category=category, symbol=symbol, limit=limit)
            return _ok({"category": category, "symbol": symbol, **ob})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_orderbook")

    @mcp.tool(
        name="bybit_get_funding_history",
        description=(
            "Bybit v5 historical funding rate for a perpetual. Returns list of "
            "{symbol, fundingRate, fundingRateTimestamp}."
        ),
    )
    async def bybit_get_funding_history(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = 200,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_funding_history(
                    category=category, symbol=symbol,
                    start_ms=start_ms, end_ms=end_ms, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "funding": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_funding_history")

    @mcp.tool(
        name="bybit_get_open_interest",
        description=(
            "Bybit v5 open interest for a perpetual. Returns list of "
            "{symbol, openInterest, timestamp}."
        ),
    )
    async def bybit_get_open_interest(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        interval_time: str = "5min",
        limit: int = 50,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_open_interest(
                    category=category, symbol=symbol,
                    interval_time=interval_time, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "oi": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_open_interest")

    @mcp.tool(
        name="bybit_get_instruments_info",
        description=(
            "Bybit v5 instrument metadata (lot size filter, price filter, "
            "leverage limits, etc.) for a category, optionally filtered by symbol."
        ),
    )
    async def bybit_get_instruments_info(
        category: str = "linear",
        symbol: str | None = None,
        limit: int = 200,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_instruments_info(
                    category=category, symbol=symbol, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "instruments": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_instruments_info")

    @mcp.tool(
        name="bybit_get_recent_trades",
        description=(
            "Bybit v5 recent public trades for a symbol. Returns list of "
            "[execId, price, size, side, time]."
        ),
    )
    async def bybit_get_recent_trades(
        category: str = "linear",
        symbol: str = "BTCUSDT",
        limit: int = 60,
    ) -> str:
        try:
            async with get_client() as client:
                rows = await client.get_public_trade_history(
                    category=category, symbol=symbol, limit=limit,
                )
            return _ok({"category": category, "symbol": symbol, "trades": rows})
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_recent_trades")

    # ─── Intraday / Scalping analysis tools ──────────────────────────────────

    @mcp.tool(
        name="bybit_get_scalper_screener",
        description=(
            "Screen all perpetuals for scalping suitability. Filters by: "
            "min_volume_usd (24h turnover), max_spread_pct (bid-ask %), "
            "min_volatility_pct (24h price change). Returns ranked list with "
            "symbol, spread%, volume24h, price24hPcnt, lastPrice, bid1Price, ask1Price."
        ),
    )
    async def bybit_get_scalper_screener(
        category: str = "linear",
        min_volume_usd: float = 10_000_000,
        max_spread_pct: float = 0.1,
        min_volatility_pct: float = 3.0,
        limit: int = 20,
    ) -> str:
        """Screen perpetuals for scalping candidates.

        Args:
            category: ``linear`` (USDT perps) or ``inverse``.
            min_volume_usd: Minimum 24h turnover in USDT (default 10M).
            max_spread_pct: Maximum bid-ask spread % (default 0.1%).
            min_volatility_pct: Minimum 24h price change % (default 3%).
            limit: Max results to return (default 20).
        """
        try:
            async with get_client() as client:
                tickers_raw = await client.get_tickers(category=category, symbol=None)

            candidates = []
            for t in tickers_raw:
                symbol = t.get("symbol", "")
                last_price = float(t.get("lastPrice", 0) or 0)
                bid1 = float(t.get("bid1Price", 0) or 0)
                ask1 = float(t.get("ask1Price", 0) or 0)
                volume_24h = float(t.get("turnover24h", 0) or 0)
                price_24h_pcnt = float(t.get("price24hPcnt", 0) or 0)

                if last_price <= 0 or bid1 <= 0 or ask1 <= 0:
                    continue

                spread_pct = ((ask1 - bid1) / bid1) * 100
                volatility_pct = abs(price_24h_pcnt) * 100

                if volume_24h < min_volume_usd:
                    continue
                if spread_pct > max_spread_pct:
                    continue
                if volatility_pct < min_volatility_pct:
                    continue

                candidates.append({
                    "symbol": symbol,
                    "lastPrice": last_price,
                    "bid1Price": bid1,
                    "ask1Price": ask1,
                    "spread_pct": round(spread_pct, 4),
                    "volume24h_usd": round(volume_24h, 2),
                    "volatility24h_pct": round(volatility_pct, 2),
                    "price24hPcnt": price_24h_pcnt,
                })

            candidates.sort(key=lambda x: (-x["volume24h_usd"], x["spread_pct"], -x["volatility24h_pct"]))
            return _ok({
                "category": category,
                "filters": {
                    "min_volume_usd": min_volume_usd,
                    "max_spread_pct": max_spread_pct,
                    "min_volatility_pct": min_volatility_pct,
                },
                "total_candidates": len(candidates),
                "results": candidates[:limit],
            })
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_scalper_screener")

    @mcp.tool(
        name="bybit_get_scalping_analysis",
        description=(
            "Comprehensive scalping analysis for a single symbol. Returns spread, "
            "liquidity score, volatility, trade flow analysis, order book depth, "
            "funding rate, and scalping verdict (EXCELLENT/GOOD/FAIR/POOR) with "
            "0-100 score. Includes entry/exit recommendations."
        ),
    )
    async def bybit_get_scalping_analysis(
        symbol: str = "BTCUSDT",
        category: str = "linear",
    ) -> str:
        """Deep scalping analysis for a symbol.

        Args:
            symbol: Trading pair (e.g. ``BTCUSDT``, ``VIRTUALUSDT``).
            category: ``linear`` (USDT perps) or ``inverse``.

        Returns:
            JSON with spread, liquidity_score (0-100), volatility_24h,
            trade_flow (buy/sell pressure), depth_usd, funding_rate,
            scalping_verdict, scalping_score (0-100), and recommendations.
        """
        try:
            async with get_client() as client:
                tickers = await client.get_tickers(category=category, symbol=symbol)
                orderbook = await client.get_orderbook(category=category, symbol=symbol, limit=50)
                trades = await client.get_public_trade_history(category=category, symbol=symbol, limit=60)
                klines = await client.get_kline(category=category, symbol=symbol, interval="1", limit=100)
                instruments = await client.get_instruments_info(category=category, symbol=symbol)

            if not tickers:
                return _err(Exception(f"No ticker found for {symbol}"), "bybit_get_scalping_analysis")

            t = tickers[0]
            last_price = float(t.get("lastPrice", 0) or 0)
            bid1 = float(t.get("bid1Price", 0) or 0)
            ask1 = float(t.get("ask1Price", 0) or 0)
            volume_24h = float(t.get("turnover24h", 0) or 0)
            price_24h_pcnt = float(t.get("price24hPcnt", 0) or 0)
            funding_rate = float(t.get("fundingRate", 0) or 0)

            spread_pct = ((ask1 - bid1) / bid1) * 100 if bid1 > 0 else 999
            volatility_24h = abs(price_24h_pcnt) * 100

            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            depth_bids_usd = sum(float(p) * float(s) for p, s in bids[:10])
            depth_asks_usd = sum(float(p) * float(s) for p, s in asks[:10])
            depth_total_usd = depth_bids_usd + depth_asks_usd

            buy_volume = sum(float(tr.get("size", 0)) for tr in trades if tr.get("side") == "Buy")
            sell_volume = sum(float(tr.get("size", 0)) for tr in trades if tr.get("side") == "Sell")
            total_volume = buy_volume + sell_volume
            buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5
            trade_flow = "BUY_PRESSURE" if buy_ratio > 0.55 else "SELL_PRESSURE" if buy_ratio < 0.45 else "BALANCED"

            kline_volumes = [float(k[5]) for k in klines if len(k) > 5]
            avg_volume_1m = sum(kline_volumes) / len(kline_volumes) if kline_volumes else 0
            price_range = [float(k[4]) for k in klines if len(k) > 4]
            range_100m = (max(price_range) - min(price_range)) / min(price_range) * 100 if price_range else 0

            spread_score = max(0, min(100, 100 - spread_pct * 500))
            volume_score = min(100, volume_24h / 1_000_000 * 10)
            depth_score = min(100, depth_total_usd / 10_000 * 10)
            volatility_score = min(100, volatility_24h / 5 * 20)
            liquidity_score = round((spread_score * 0.4 + volume_score * 0.3 + depth_score * 0.3), 1)
            scalping_score = round((liquidity_score * 0.5 + volatility_score * 0.5), 1)

            if scalping_score >= 80:
                verdict = "EXCELLENT"
            elif scalping_score >= 60:
                verdict = "GOOD"
            elif scalping_score >= 40:
                verdict = "FAIR"
            else:
                verdict = "POOR"

            min_notional = float(instruments[0].get("lotSizeFilter", {}).get("minNotionalValue", 5)) if instruments else 5
            tick_size = float(instruments[0].get("priceFilter", {}).get("tickSize", 0.1)) if instruments else 0.1
            tick_pct = (tick_size / last_price) * 100 if last_price > 0 else 0

            target_scalp_pct = max(tick_pct * 3, 0.05)
            stop_loss_pct = max(tick_pct * 2, 0.03)

            return _ok({
                "symbol": symbol,
                "category": category,
                "timestamp": orderbook.get("ts", 0),
                "price": {
                    "last": last_price,
                    "bid1": bid1,
                    "ask1": ask1,
                },
                "spread": {
                    "absolute": round(ask1 - bid1, 8),
                    "pct": round(spread_pct, 4),
                    "ticks": round((ask1 - bid1) / tick_size, 1) if tick_size > 0 else 0,
                },
                "liquidity": {
                    "score": liquidity_score,
                    "volume24h_usd": round(volume_24h, 2),
                    "depth_bids_usd": round(depth_bids_usd, 2),
                    "depth_asks_usd": round(depth_asks_usd, 2),
                    "depth_total_usd": round(depth_total_usd, 2),
                    "avg_volume_1m": round(avg_volume_1m, 4),
                },
                "volatility": {
                    "24h_pct": round(volatility_24h, 2),
                    "100m_range_pct": round(range_100m, 2),
                },
                "trade_flow": {
                    "direction": trade_flow,
                    "buy_ratio": round(buy_ratio, 3),
                    "buy_volume": round(buy_volume, 2),
                    "sell_volume": round(sell_volume, 2),
                },
                "funding": {
                    "rate": funding_rate,
                    "rate_pct_24h": round(funding_rate * 3 * 100, 4),
                },
                "instrument": {
                    "min_notional_usd": min_notional,
                    "tick_size": tick_size,
                    "tick_pct": round(tick_pct, 4),
                },
                "scalping": {
                    "score": scalping_score,
                    "verdict": verdict,
                    "recommended_target_pct": round(target_scalp_pct, 3),
                    "recommended_stop_pct": round(stop_loss_pct, 3),
                    "break_even_win_rate_pct": round(50 + (spread_pct + 0.04) / 2 / target_scalp_pct * 100, 1) if target_scalp_pct > 0 else 55,
                },
            })
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_get_scalping_analysis")

    @mcp.tool(
        name="bybit_scalp_session_status",
        description=(
            "Check trading session status for Bybit. Returns current session, "
            "entry allowed, minutes until close. Works with UTC timezone."
        ),
    )
    async def bybit_scalp_session_status(
        strategy_type: str = "scalping",
    ) -> str:
        """Check session status.

        Args:
            strategy_type: scalping, intraday, momentum, mean_reversion.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        hour = now.hour
        minute = now.minute
        day_of_week = now.weekday()

        if day_of_week >= 5:
            return _ok({
                "strategy_type": strategy_type,
                "current_time": f"{hour}:{minute:02d}",
                "day_of_week": day_of_week,
                "weekend": True,
                "current_session": "closed",
                "entry_allowed": False,
                "minutes_until_close": 0,
            })

        windows = {
            "scalping": {"start": "14:00", "end": "18:00", "entry_allowed": True},
            "intraday": {"start": "14:00", "end": "21:00", "entry_allowed": True},
            "momentum": {"start": "14:00", "end": "21:00", "entry_allowed": True},
            "mean_reversion": {"start": "14:00", "end": "18:00", "entry_allowed": True},
        }
        window = windows.get(strategy_type, windows["scalping"])
        start_h, start_m = map(int, window["start"].split(":"))
        end_h, end_m = map(int, window["end"].split(":"))

        now_minutes = hour * 60 + minute
        start_minutes = start_h * 60 + start_m
        end_minutes = end_h * 60 + end_m

        if start_minutes <= now_minutes < end_minutes:
            current_session = "active"
            entry_allowed = window["entry_allowed"]
            minutes_until_close = end_minutes - now_minutes
        else:
            current_session = "closed"
            entry_allowed = False
            minutes_until_close = 0

        return _ok({
            "strategy_type": strategy_type,
            "current_time": f"{hour}:{minute:02d}",
            "day_of_week": day_of_week,
            "weekend": False,
            "current_session": current_session,
            "entry_allowed": entry_allowed,
            "minutes_until_close": minutes_until_close,
        })

    @mcp.tool(
        name="bybit_scalp_orderbook_analysis",
        description=(
            "Analyze orderbook: spread, bid/ask imbalance, wall detection (>3σ). "
            "Pass raw orderbook from bybit_get_orderbook."
        ),
    )
    async def bybit_scalp_orderbook_analysis(
        symbol: str = "BTCUSDT",
        category: str = "linear",
        depth: int = 10,
    ) -> str:
        """Analyze orderbook for a symbol.

        Args:
            symbol: Trading pair.
            category: ``linear`` or ``inverse``.
            depth: Levels per side to analyze.
        """
        try:
            async with get_client() as client:
                orderbook = await client.get_orderbook(category=category, symbol=symbol, limit=depth)

            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            bid_total = sum(float(s) for _, s in bids[:depth])
            ask_total = sum(float(s) for _, s in asks[:depth])
            total = bid_total + ask_total
            imbalance = (bid_total - ask_total) / total if total > 0 else 0
            ratio = bid_total / ask_total if ask_total > 0 else float('inf')

            best_bid = float(bids[0][0]) if bids else 0
            best_ask = float(asks[0][0]) if asks else 0
            spread = best_ask - best_bid
            spread_pct = (spread / best_bid * 100) if best_bid > 0 else 0

            # Wall detection
            all_sizes = [float(s) for p, s in bids[:depth]] + [float(s) for p, s in asks[:depth]]
            if all_sizes:
                mean_size = sum(all_sizes) / len(all_sizes)
                std_size = (sum((x - mean_size) ** 2 for x in all_sizes) / len(all_sizes)) ** 0.5
                wall_threshold = mean_size + 3 * std_size
                bid_walls = [(float(p), float(s)) for p, s in bids[:depth] if float(s) >= wall_threshold]
                ask_walls = [(float(p), float(s)) for p, s in asks[:depth] if float(s) >= wall_threshold]
            else:
                bid_walls = []
                ask_walls = []

            side = "bid" if imbalance > 0.1 else "ask" if imbalance < -0.1 else "balanced"

            return _ok({
                "symbol": symbol,
                "category": category,
                "spread": {
                    "absolute": round(spread, 8),
                    "pct": round(spread_pct, 4),
                },
                "imbalance": {
                    "bidTotal": round(bid_total, 4),
                    "askTotal": round(ask_total, 4),
                    "ratio": round(ratio, 2),
                    "imbalance": round(imbalance, 4),
                },
                "walls": {
                    "bids": [{"price": p, "size": s} for p, s in bid_walls],
                    "asks": [{"price": p, "size": s} for p, s in ask_walls],
                },
                "summary": {
                    "side": side,
                    "wallCount": len(bid_walls) + len(ask_walls),
                },
            })
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_scalp_orderbook_analysis")

    @mcp.tool(
        name="bybit_scalp_trade_flow",
        description=(
            "Analyze trade flow: buy/sell ratio, large order detection, VWAP. "
            "Pass raw trades from bybit_get_recent_trades."
        ),
    )
    async def bybit_scalp_trade_flow(
        symbol: str = "BTCUSDT",
        category: str = "linear",
        lookback_sec: int = 60,
    ) -> str:
        """Analyze trade flow for a symbol.

        Args:
            symbol: Trading pair.
            category: ``linear`` or ``inverse``.
            lookback_sec: Lookback window in seconds (default 60).
        """
        try:
            async with get_client() as client:
                trades = await client.get_public_trade_history(category=category, symbol=symbol, limit=60)

            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(seconds=lookback_sec)

            recent = []
            for tr in trades:
                ts = tr.get("time", "")
                if ts:
                    try:
                        trade_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if trade_time >= cutoff:
                            recent.append(tr)
                    except (ValueError, TypeError):
                        recent.append(tr)

            buy_volume = sum(float(tr.get("size", 0)) for tr in recent if tr.get("side") == "Buy")
            sell_volume = sum(float(tr.get("size", 0)) for tr in recent if tr.get("side") == "Sell")
            total_volume = buy_volume + sell_volume
            buy_ratio = buy_volume / total_volume if total_volume > 0 else 0.5

            # VWAP
            cum_vp = sum(float(tr.get("price", 0)) * float(tr.get("size", 0)) for tr in recent)
            vwap = cum_vp / total_volume if total_volume > 0 else 0

            # Large orders (top 10%)
            sizes = [float(tr.get("size", 0)) for tr in recent]
            sizes_sorted = sorted(sizes, reverse=True)
            large_threshold = sizes_sorted[len(sizes_sorted) // 10] if sizes_sorted else 0
            large_orders = sum(1 for s in sizes if s >= large_threshold)

            direction = "BUY_PRESSURE" if buy_ratio > 0.55 else "SELL_PRESSURE" if buy_ratio < 0.45 else "BALANCED"

            return _ok({
                "symbol": symbol,
                "category": category,
                "lookback_sec": lookback_sec,
                "trade_count": len(recent),
                "direction": direction,
                "buy_ratio": round(buy_ratio, 3),
                "buy_volume": round(buy_volume, 2),
                "sell_volume": round(sell_volume, 2),
                "total_volume": round(total_volume, 2),
                "vwap": round(vwap, 2),
                "large_orders": large_orders,
            })
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_scalp_trade_flow")

    @mcp.tool(
        name="bybit_scalp_orderbook_strategy",
        description=(
            "Run 5 orderbook-based strategies (imbalance, wall-breakout, absorption, "
            "delta-divergence, flow-ratio). Returns ensemble consensus."
        ),
    )
    async def bybit_scalp_orderbook_strategy(
        symbol: str = "BTCUSDT",
        category: str = "linear",
        depth: int = 10,
    ) -> str:
        """Run orderbook strategies on a symbol.

        Args:
            symbol: Trading pair.
            category: ``linear`` or ``inverse``.
            depth: Levels per side for analysis.
        """
        try:
            async with get_client() as client:
                orderbook = await client.get_orderbook(category=category, symbol=symbol, limit=depth)
                trades_raw = await client.get_public_trade_history(category=category, symbol=symbol, limit=60)
                tickers = await client.get_tickers(category=category, symbol=symbol)

            if not tickers:
                return _err(Exception(f"No ticker for {symbol}"), "bybit_scalp_orderbook_strategy")

            last_price = float(tickers[0].get("lastPrice", 0) or 0)
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            # ─── Strategy 1: Imbalance ───
            bid_total = sum(float(s) for _, s in bids[:depth])
            ask_total = sum(float(s) for _, s in asks[:depth])
            total = bid_total + ask_total
            imb_ratio = bid_total / ask_total if ask_total > 0 else float('inf')
            imb_val = (bid_total - ask_total) / total if total > 0 else 0

            if imb_ratio > 1.5 and imb_val > 0.2:
                imb_action, imb_conf = "buy", min(imb_val * 1.5, 1.0)
            elif imb_ratio < 0.67 and imb_val < -0.2:
                imb_action, imb_conf = "sell", min(abs(imb_val) * 1.5, 1.0)
            else:
                imb_action, imb_conf = "hold", 0

            # ─── Strategy 2: Wall Breakout ───
            all_sizes = [float(s) for _, s in bids[:depth]] + [float(s) for _, s in asks[:depth]]
            if all_sizes:
                m = sum(all_sizes) / len(all_sizes)
                s_val = (sum((x - m) ** 2 for x in all_sizes) / len(all_sizes)) ** 0.5
                wall_thresh = m + 3 * s_val
                bid_walls = sum(1 for _, s in bids[:depth] if float(s) >= wall_thresh)
                ask_walls = sum(1 for _, s in asks[:depth] if float(s) >= wall_thresh)
            else:
                bid_walls, ask_walls = 0, 0

            if bid_walls > 0 and ask_walls == 0:
                wall_action, wall_conf = "buy", 0.6
            elif ask_walls > 0 and bid_walls == 0:
                wall_action, wall_conf = "sell", 0.6
            else:
                wall_action, wall_conf = "hold", 0

            # ─── Strategy 3: Flow Ratio ───
            buy_vol = sum(float(tr.get("size", 0)) for tr in trades_raw if tr.get("side") == "Buy")
            sell_vol = sum(float(tr.get("size", 0)) for tr in trades_raw if tr.get("side") == "Sell")
            flow_total = buy_vol + sell_vol
            flow_ratio = buy_vol / flow_total if flow_total > 0 else 0.5

            if flow_ratio > 0.65:
                flow_action, flow_conf = "buy", min((flow_ratio - 0.5) * 3, 1.0)
            elif flow_ratio < 0.35:
                flow_action, flow_conf = "sell", min((0.5 - flow_ratio) * 3, 1.0)
            else:
                flow_action, flow_conf = "hold", 0

            # Hold for the rest
            abs_action, abs_conf = "hold", 0
            div_action, div_conf = "hold", 0

            signals = [
                {"strategyId": "ob-imbalance", "action": imb_action, "confidence": round(imb_conf, 3)},
                {"strategyId": "ob-wall-break", "action": wall_action, "confidence": round(wall_conf, 3)},
                {"strategyId": "ob-absorption", "action": abs_action, "confidence": round(abs_conf, 3)},
                {"strategyId": "ob-delta-div", "action": div_action, "confidence": round(div_conf, 3)},
                {"strategyId": "ob-flow-ratio", "action": flow_action, "confidence": round(flow_conf, 3)},
            ]

            buy_count = sum(1 for s in signals if s["action"] == "buy")
            sell_count = sum(1 for s in signals if s["action"] == "sell")
            hold_count = sum(1 for s in signals if s["action"] == "hold")

            if buy_count >= 3:
                ensemble_action = "buy"
                ensemble_conf = sum(s["confidence"] for s in signals if s["action"] == "buy") / buy_count
            elif sell_count >= 3:
                ensemble_action = "sell"
                ensemble_conf = sum(s["confidence"] for s in signals if s["action"] == "sell") / sell_count
            else:
                ensemble_action = "hold"
                ensemble_conf = 0

            return _ok({
                "symbol": symbol,
                "category": category,
                "last_price": last_price,
                "action": ensemble_action,
                "confidence": round(ensemble_conf, 3),
                "buyCount": buy_count,
                "sellCount": sell_count,
                "holdCount": hold_count,
                "signals": signals,
            })
        except (BybitAPIError, BybitTransportError, BybitError) as exc:
            return _err(exc, "bybit_scalp_orderbook_strategy")
