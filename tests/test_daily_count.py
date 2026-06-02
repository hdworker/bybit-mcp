"""Daily counter tests (UTC rollover, atomic)."""

from __future__ import annotations

import json

from bybit_mcp.safety.daily_count import (
    increment_daily_count,
    read_daily_count,
)


def test_read_zero_when_missing(tmp_runtime_root):
    assert read_daily_count("bybit") == 0


def test_increment_and_read(tmp_runtime_root):
    assert increment_daily_count("bybit") == 1
    assert read_daily_count("bybit") == 1
    assert increment_daily_count("bybit") == 2
    assert read_daily_count("bybit") == 2


def test_rollover_when_date_stale(tmp_runtime_root):
    path = tmp_runtime_root / "live" / "bybit" / "trade_counter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": "2000-01-01", "count": 99}), encoding="utf-8")
    # Stale date → reads as 0 (UTC rollover), next increment starts fresh.
    assert read_daily_count("bybit") == 0
    assert increment_daily_count("bybit") == 1


def test_per_broker_isolated(tmp_runtime_root):
    increment_daily_count("bybit")
    increment_daily_count("bybit")
    increment_daily_count("okx")
    assert read_daily_count("bybit") == 2
    assert read_daily_count("okx") == 1


def test_malformed_counter_reads_zero(tmp_runtime_root):
    path = tmp_runtime_root / "live" / "bybit" / "trade_counter.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert read_daily_count("bybit") == 0
