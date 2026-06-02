"""FastMCP server package for bybit-mcp.

Tool surface (14 tools):

**Read (no mandate gate)**:
    bybit_get_tickers, bybit_get_kline, bybit_get_orderbook,
    bybit_get_funding_history, bybit_get_open_interest,
    bybit_get_instruments_info, bybit_get_wallet_balance,
    bybit_get_positions, bybit_get_open_orders, bybit_get_order_history,
    bybit_get_recent_trades

**Write (gated by MandateGate)**:
    bybit_place_order, bybit_amend_order, bybit_cancel_order,
    bybit_cancel_all_orders, bybit_set_leverage, bybit_set_trading_stop
"""
