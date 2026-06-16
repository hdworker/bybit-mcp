# bybit-mcp

[![CI](https://github.com/hdworker/bybit-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/hdworker/bybit-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/bybit-go-mcp.svg)](https://pypi.org/project/bybit-go-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

MCP-сервер для Bybit v5 — рыночные данные, аккаунт, ордера и инструменты скальпинга/интрадея.

---

Bybit v5 broker MCP server — market data, account, orders, and scalping/intraday tools for [scalp-lab](https://github.com/hdworker/scalp-lab).

---

## Quick start

```bash
# 1. Install
cd ~/eth/bybit-mcp
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
$EDITOR .env                  # set BYBIT_API_KEY / BYBIT_API_SECRET

# 3. Run (stdio for MCP embedding)
python -m bybit_mcp.server.mcp_server --transport stdio

# 3b. Or run over HTTP for testing
python -m bybit_mcp.server.mcp_server --transport http --port 8001
```

## Архитектура

```
+------------------+      stdio/HTTP      +------------------+
|   scalp-lab MCP  | <------------------> |   bybit-mcp      |
|   (analytics)    |                      |   (data + tools) |
+------------------+                      +--------+---------+
                                                   |
                                          +--------v---------+
                                          |   Bybit v5 API   |
                                          +------------------+
```

**bybit-mcp** — чистый data provider. Вся аналитика (scoring, strategies, verdict) — в scalp-lab MCP.

---

## ДАННЫЕ

### Рыночные данные (7 tools)

| Tool | Описание |
|------|----------|
| `bybit_get_tickers` | Тикеры: lastPrice, bid1, ask1, volume24h, price24hPcnt, fundingRate, openInterest |
| `bybit_get_kline` | Свечи (K-line): interval 1m–MN, до 1000 свечей за запрос |
| `bybit_get_orderbook` | Стакан (L2): bids/asks по 5–50 уровней |
| `bybit_get_funding_history` | История funding rate: rate + timestamp |
| `bybit_get_open_interest` | Открытый интерес: volume + timestamp |
| `bybit_get_instruments_info` | Мета-инструмента: lotSizeFilter, priceFilter, leverage limits |
| `bybit_get_recent_trades` | Последние 60 сделок: price, size, side, time |

### Аккаунт (4 tools)

| Tool | Описание |
|------|----------|
| `bybit_get_wallet_balance` | Баланс: per-coin equity, walletBalance, unrealisedPnl |
| `bybit_get_positions` | Открытые позиции: symbol, side, size, avgPrice, liqPrice, leverage |
| `bybit_get_open_orders` | Активные ордера: orderId, side, type, price, qty, status |
| `bybit_get_order_history` | История ордёров (до 2 лет): все поля + createdTime, cumExecFee |

### Ордера (6 tools)

| Tool | Описание |
|------|----------|
| `bybit_place_order` | Размещение: Limit/Market/Stop, gated by mandate |
| `bybit_amend_order` | Изменение: price/qty/TP/SL, enforce LARGER notional |
| `bybit_cancel_order` | Отмена одного ордера |
| `bybit_cancel_all_orders` | Массовая отмена (все или по символу) |
| `bybit_set_leverage` | Установка плеча (structural check) |
| `bybit_set_trading_stop` | TP/SL на позицию |

---

## СКАЛЬПИНГ / ИНТРАДЕЙ

### Скринер — `bybit_get_scalper_screener`

Сканирует все perpetuals и фильтрует по критериям скальпинга.

**Фильтры:**
- `min_volume_usd` — минимальный 24h turnover (по умолчанию 10M USDT)
- `max_spread_pct` — максимальный bid-ask spread (по умолчанию 0.1%)
- `min_volatility_pct` — минимальная 24h волатильность (по умолчанию 3%)

**Логика:**
```
spread_pct = (ask1 - bid1) / bid1 × 100
volatility_pct = abs(price24hPcnt) × 100
```

**Сортировка:** volume DESC → spread ASC → volatility DESC

**Возвращает:** symbol, lastPrice, bid1, ask1, spread%, volume24h, volatility%, price24hPcnt

---

### Анализ — `bybit_get_scalping_analysis`

Комплексный анализ одного тикера: spread, ликвидность, глубина стакана, флоу, funding, вердикт.

**Формулы:**
```
spread_score = clamp(100 - spread_pct × 500, 0, 100)
volume_score = min(100, volume_24h / 1M × 10)
depth_score  = min(100, depth_total_usd / 10K × 10)

liquidity_score = spread_score × 0.4 + volume_score × 0.3 + depth_score × 0.3
volatility_score = min(100, volatility_24h / 5 × 20)

scalping_score = liquidity_score × 0.5 + volatility_score × 0.5
```

**Вердикт:**
| Score | Verdict |
|-------|---------|
| ≥ 80 | EXCELLENT |
| ≥ 60 | GOOD |
| ≥ 40 | FAIR |
| < 40 | POOR |

**Возвращает:** spread, liquidity (score + depth_usd), volatility (24h% + 100m_range%), trade_flow (direction + ratio), funding (rate + rate_24h%), scalping (score + verdict + recommended target/stop%)

---

### Сессия — `bybit_scalp_session_status`

Проверяет текущую торговую сессию (UTC).

**Окна:**
| Стратегия | Начало | Конец | Entry allowed |
|-----------|--------|-------|---------------|
| scalping | 14:00 | 18:00 | ✅ |
| intraday | 14:00 | 21:00 | ✅ |
| momentum | 14:00 | 21:00 | ✅ |
| mean_reversion | 14:00 | 18:00 | ✅ |

**Возвращает:** current_session (active/closed), entry_allowed, minutes_until_close, weekend

---

### Ордербук-анализ — `bybit_scalp_orderbook_analysis`

Анализ стакана: spread, imbalance, обнаружение стен.

**Формулы:**
```
imbalance = (bidTotal - askTotal) / (bidTotal + askTotal)
ratio     = bidTotal / askTotal
spread    = (ask - bid) / bid × 100
```

**Стены (walls):**
```
all_sizes = [bid sizes] + [ask sizes]
threshold = mean(all_sizes) + 3 × std(all_sizes)
```
Всё, что ≥ threshold — стена.

**Возвращает:** spread (absolute + pct), imbalance (bidTotal, askTotal, ratio, imbalance), walls (bids[], asks[]), summary (side + wallCount)

---

### Трейд-флоу — `bybit_scalp_trade_flow`

Анализ потока сделок: buy/sell ratio, VWAP, крупные ордера.

**Формулы:**
```
buy_ratio  = buyVolume / (buyVolume + sellVolume)
vwap       = Σ(price × size) / Σ(size)
```

**Определение направления:**
| buy_ratio | Direction |
|-----------|-----------|
| > 0.55 | BUY_PRESSURE |
| < 0.45 | SELL_PRESSURE |
| 0.45–0.55 | BALANCED |

**Крупные ордера:** top 10% по размеру за lookbackSec.

**Возвращает:** direction, buy_ratio, buy_volume, sell_volume, vwap, large_orders

---

### Ордербук-стратегии — `bybit_scalp_orderbook_strategy`

5 микроструктурных стратегий → ensemble consensus.

**Стратегии:**

| # | ID | Логика | Действие |
|---|-----|--------|----------|
| 1 | ob-imbalance | ratio > 1.5 и imbalance > 0.2 → buy; ratio < 0.67 и imbalance < -0.2 → sell | buy/sell/hold |
| 2 | ob-wall-break | Стены только на одной стороне (3σ) → buy/sell | buy/sell/hold |
| 3 | ob-absorption | Заглушка (stub) | hold |
| 4 | ob-delta-div | Заглушка (stub) | hold |
| 5 | ob-flow-ratio | buy_ratio > 65% → buy; < 35% → sell | buy/sell/hold |

**Ensemble:**
- ≥ 3 strategies agree → consensus action + average confidence
- Иначе → hold

**Возвращает:** action (buy/sell/hold), confidence, buyCount, sellCount, holdCount, signals[]

---

## Environment

| Var | Default | Purpose |
|-----|---------|---------|
| `BYBIT_API_KEY` | (empty = public-only) | Bybit API key |
| `BYBIT_API_SECRET` | (empty) | Bybit API secret |
| `BYBIT_TESTNET` | `false` | Use testnet base URL |
| `BYBIT_HTTP_TIMEOUT` | `10` | httpx request timeout (seconds) |
| `BYBIT_RECV_WINDOW` | `5000` | recv_window for signed requests (ms) |
| `BYBIT_BROKER_KEY` | `bybit` | Per-broker path key |
| `BYBIT_MCP_LOG_LEVEL` | `INFO` | Logger level |
| `BYBIT_MCP_HOST` | `127.0.0.1` | HTTP host (when `--transport http`) |
| `BYBIT_MCP_PORT` | `8001` | HTTP port (when `--transport http`) |

## Development

```bash
make install       # pip install -e ".[dev]"
make test          # pytest
make lint          # ruff check
make format        # black + ruff --fix
make run-stdio     # stdio transport
make run-sse       # HTTP transport on :8001
```

## Install from PyPI

```bash
pip install bybit-go-mcp
bybit-mcp --help
```

## License

MIT
