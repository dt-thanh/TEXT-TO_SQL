"""Unit tests for kline parsing and pagination, against an in-memory fake of Binance."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.common.exceptions import SourceAPIError
from src.ingestion.binance.extractor import extract_klines, ms_to_utc, parse_kline, to_ms

HOUR = timedelta(hours=1)
HOUR_MS = 3_600_000
T0 = datetime(2024, 1, 1, tzinfo=UTC)
LONG_AFTER = T0 + timedelta(days=30)


def raw_row(open_ms: int, close: str = "100.0") -> list[Any]:
    """A Binance-shaped 1h row: numbers arrive as strings, times as epoch milliseconds."""

    return [
        open_ms, "99.0", "101.0", "98.0", close, "10.5",
        open_ms + HOUR_MS - 1, "1050.0", 42, "5.25", "525.0", "0",
    ]  # fmt: skip


class FakeBinance:
    """Serves `hours` consecutive 1h candles from T0, with Binance's inclusive endTime rule."""

    def __init__(self, hours: int) -> None:
        self.rows = [raw_row(to_ms(T0 + h * HOUR)) for h in range(hours)]
        self.calls: list[tuple[int, int]] = []

    def get_klines(
        self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int
    ) -> list[list[Any]]:
        self.calls.append((start_ms, end_ms))
        return [row for row in self.rows if start_ms <= row[0] <= end_ms][:limit]


def open_times(klines: list[Any]) -> list[datetime]:
    return [kline.open_time for kline in klines]


def test_ms_to_utc_is_exact_to_the_millisecond() -> None:
    assert ms_to_utc(1704070799999) == datetime(2024, 1, 1, 0, 59, 59, 999000, tzinfo=UTC)


def test_to_ms_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="no timezone"):
        to_ms(datetime(2024, 1, 1))


def test_parse_kline_maps_positions_and_types() -> None:
    kline = parse_kline("BTCUSDT", "1h", raw_row(to_ms(T0), close="42475.23"))

    assert kline.open_time == T0
    assert kline.close_time == T0 + HOUR - timedelta(milliseconds=1)
    assert kline.close_price == Decimal("42475.23")
    assert kline.quote_volume == Decimal("1050.0")
    assert kline.trade_count == 42
    assert kline.taker_buy_quote_volume == Decimal("525.0")


def test_parse_kline_rejects_malformed_row() -> None:
    with pytest.raises(SourceAPIError, match="Unexpected Binance kline row"):
        parse_kline("BTCUSDT", "1h", [1704067200000, "42283.58"])


def test_paginates_until_the_window_is_covered() -> None:
    fake = FakeBinance(hours=5)

    klines = extract_klines(fake, "BTCUSDT", "1h", T0, T0 + 5 * HOUR, LONG_AFTER, page_size=2)

    assert open_times(klines) == [T0 + h * HOUR for h in range(5)]
    # Each page starts 1 ms after the previous page's last open time.
    assert [start for start, _ in fake.calls] == [
        to_ms(T0),
        to_ms(T0 + 1 * HOUR) + 1,
        to_ms(T0 + 3 * HOUR) + 1,
    ]


def test_window_is_half_open() -> None:
    fake = FakeBinance(hours=10)

    klines = extract_klines(fake, "BTCUSDT", "1h", T0, T0 + 3 * HOUR, LONG_AFTER)

    assert open_times(klines) == [T0, T0 + HOUR, T0 + 2 * HOUR]
    assert fake.calls[0][1] == to_ms(T0 + 3 * HOUR) - 1


def test_back_to_back_windows_neither_overlap_nor_leave_gaps() -> None:
    fake = FakeBinance(hours=6)

    first = extract_klines(fake, "BTCUSDT", "1h", T0, T0 + 3 * HOUR, LONG_AFTER)
    second = extract_klines(fake, "BTCUSDT", "1h", T0 + 3 * HOUR, T0 + 6 * HOUR, LONG_AFTER)

    assert open_times(first + second) == [T0 + h * HOUR for h in range(6)]


def test_drops_candle_still_in_progress() -> None:
    fake = FakeBinance(hours=3)
    now = T0 + 2 * HOUR + timedelta(minutes=30)

    klines = extract_klines(fake, "BTCUSDT", "1h", T0, T0 + 3 * HOUR, now)

    assert open_times(klines) == [T0, T0 + HOUR]


def test_start_before_listing_returns_from_first_candle() -> None:
    fake = FakeBinance(hours=2)
    a_year_earlier = T0 - timedelta(days=365)

    klines = extract_klines(fake, "SOLUSDT", "1h", a_year_earlier, T0 + 2 * HOUR, LONG_AFTER)

    assert open_times(klines) == [T0, T0 + HOUR]


def test_refuses_to_loop_forever_when_pages_stop_advancing() -> None:
    class StuckBinance:
        def get_klines(self, *args: object) -> list[list[Any]]:
            return [raw_row(to_ms(T0))]

    with pytest.raises(SourceAPIError, match="stopped advancing"):
        extract_klines(StuckBinance(), "BTCUSDT", "1h", T0, T0 + 5 * HOUR, LONG_AFTER, page_size=1)
