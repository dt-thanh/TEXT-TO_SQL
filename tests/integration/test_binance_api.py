"""Integration test against the real Binance API: checks our reading of its time rules."""

from datetime import UTC, datetime, timedelta

from src.ingestion.binance.client import BinanceClient
from src.ingestion.binance.extractor import extract_klines


def test_past_window_returns_exactly_its_hours() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)

    with BinanceClient() as client:
        klines = extract_klines(client, "BTCUSDT", "1h", start, end)

    assert [k.open_time for k in klines] == [start + timedelta(hours=h) for h in range(3)]
    for kline in klines:
        assert kline.close_time == kline.open_time + timedelta(hours=1, milliseconds=-1)
        assert kline.low_price <= kline.close_price <= kline.high_price
