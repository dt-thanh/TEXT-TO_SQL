"""Unit tests for watermark planning and month-by-month loading."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from src.ingestion.binance import sync
from src.ingestion.binance.extractor import to_ms
from src.ingestion.binance.loader import LoadResult
from src.ingestion.binance.sync import (
    BACKFILL_START,
    INCREMENTAL_LOOKBACK,
    get_watermark,
    incremental_start,
    load_window,
    month_windows,
    sync_symbol,
)

HOUR = timedelta(hours=1)
HOUR_MS = 3_600_000
NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- month_windows: pure function, no I/O -------------------------------------------------


def test_month_windows_cut_at_month_boundaries() -> None:
    assert month_windows(utc(2024, 1, 15, 6), utc(2024, 3, 10)) == [
        (utc(2024, 1, 15, 6), utc(2024, 2, 1)),
        (utc(2024, 2, 1), utc(2024, 3, 1)),
        (utc(2024, 3, 1), utc(2024, 3, 10)),
    ]


def test_month_windows_cross_the_year_boundary() -> None:
    assert month_windows(utc(2023, 12, 20), utc(2024, 1, 5)) == [
        (utc(2023, 12, 20), utc(2024, 1, 1)),
        (utc(2024, 1, 1), utc(2024, 1, 5)),
    ]


def test_month_windows_are_empty_when_nothing_to_load() -> None:
    assert month_windows(utc(2024, 1, 1), utc(2024, 1, 1)) == []


def test_month_windows_reject_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        month_windows(datetime(2024, 1, 1), utc(2024, 2, 1))


# --- incremental_start: pure function ----------------------------------------------------


def test_first_run_backfills_all_history() -> None:
    assert incremental_start(None) == BACKFILL_START


def test_later_runs_continue_from_watermark_minus_lookback() -> None:
    watermark = utc(2026, 9, 27, 10)

    assert incremental_start(watermark) == watermark - INCREMENTAL_LOOKBACK


# --- functions that talk to Snowflake / Binance, tested with fakes ------------------------


class FakeCursor:
    def __init__(self, value: Any) -> None:
        self.value = value
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute(self, sql: str, params: dict[str, str]) -> "FakeCursor":
        self.calls.append((sql, params))
        return self

    def fetchone(self) -> tuple[Any]:
        return (self.value,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def test_get_watermark_reads_max_open_time_for_the_symbol() -> None:
    cursor = FakeCursor(utc(2024, 1, 7, 23))

    assert get_watermark(FakeConnection(cursor), "BTCUSDT", "1h") == utc(2024, 1, 7, 23)
    sql, params = cursor.calls[0]
    assert "MAX(open_time)" in sql
    assert params == {"symbol": "BTCUSDT", "interval": "1h"}


class HourlySource:
    """Serves one 1h candle per hour from `first` for `hours` hours, like Binance would."""

    def __init__(self, first: datetime, hours: int) -> None:
        self.opens = [to_ms(first + h * HOUR) for h in range(hours)]

    def get_klines(
        self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int
    ) -> list[list[Any]]:
        opens = [o for o in self.opens if start_ms <= o <= end_ms][:limit]
        return [[o, "1", "1", "1", "1", "1", o + HOUR_MS - 1, "1", 1, "1", "1", "0"] for o in opens]


def test_load_window_loads_each_month_separately(monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[list[datetime]] = []

    def fake_load(conn: Any, klines: list[Any], batch_id: str) -> LoadResult:
        loaded.append([k.open_time for k in klines])
        return LoadResult(batch_id, len(klines), len(klines), 0)

    monkeypatch.setattr(sync, "load_klines", fake_load)
    source = HourlySource(utc(2024, 1, 31, 22), hours=4)  # 22:00, 23:00 Jan; 00:00, 01:00 Feb

    result = load_window(source, None, "BTCUSDT", "1h", utc(2024, 1, 31), utc(2024, 2, 2), NOW)

    assert loaded == [
        [utc(2024, 1, 31, 22), utc(2024, 1, 31, 23)],
        [utc(2024, 2, 1, 0), utc(2024, 2, 1, 1)],
    ]
    assert (result.months, result.rows_received, result.rows_inserted) == (2, 4, 4)


@pytest.mark.parametrize(
    ("watermark", "expected_start"),
    [
        (None, BACKFILL_START),
        (utc(2026, 9, 27, 10), utc(2026, 9, 26, 10)),
    ],
)
def test_sync_symbol_loads_from_planned_start_to_now(
    monkeypatch: pytest.MonkeyPatch, watermark: datetime | None, expected_start: datetime
) -> None:
    windows: list[tuple[datetime, datetime]] = []
    monkeypatch.setattr(sync, "get_watermark", lambda conn, symbol, interval: watermark)
    monkeypatch.setattr(
        sync,
        "load_window",
        lambda source, conn, symbol, interval, start, end, now: windows.append((start, end)),
    )

    sync_symbol(None, None, "BTCUSDT", "1h", NOW)

    assert windows == [(expected_start, NOW)]
