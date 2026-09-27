"""Unit tests for parsing FRED payloads and splitting real time into requests."""

from datetime import UTC, date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from src.common.exceptions import SourceAPIError
from src.ingestion.fred.extractor import (
    OPEN_END,
    FredObservation,
    extract_changes,
    parse_changes,
    parse_series,
    parse_value,
    year_windows,
)

# Real output_type=3 rows (FRED, September 2026): CPI for Aug 2024 was published three times.
CPI_ROWS = [
    {
        "date": "2024-08-01",
        "CPIAUCSL_20240911": "314.121",
        "CPIAUCSL_20250212": "314.131",
        "CPIAUCSL_20260213": "314.062",
    }
]


def test_dot_means_no_value_that_day() -> None:
    assert parse_value(".") is None
    assert parse_value("4.52") == Decimal("4.52")


def test_every_vintage_of_a_date_becomes_its_own_row() -> None:
    rows = parse_changes("CPIAUCSL", CPI_ROWS)

    assert [(r.realtime_start, r.value) for r in rows] == [
        (date(2024, 9, 11), Decimal("314.121")),
        (date(2025, 2, 12), Decimal("314.131")),
        (date(2026, 2, 13), Decimal("314.062")),
    ]
    assert {r.observation_date for r in rows} == {date(2024, 8, 1)}


def test_holiday_keeps_raw_text_and_null_value() -> None:
    (row,) = parse_changes("DGS10", [{"date": "2024-12-25", "DGS10_20241227": "."}])

    assert row == FredObservation("DGS10", date(2024, 12, 25), date(2024, 12, 27), ".", None)


def test_columns_of_another_series_are_rejected() -> None:
    with pytest.raises(SourceAPIError, match="does not belong"):
        parse_changes("DGS10", [{"date": "2024-12-25", "DFF_20241227": "4.33"}])


def test_series_last_updated_keeps_its_us_central_offset() -> None:
    payload = {
        "seriess": [
            {
                "id": "DGS10",
                "title": "Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity",
                "frequency": "Daily",
                "frequency_short": "D",
                "units": "Percent",
                "seasonal_adjustment": "Not Seasonally Adjusted",
                "observation_start": "1962-01-02",
                "observation_end": "2026-09-24",
                "last_updated": "2026-09-25 15:16:33-05",
            }
        ]
    }

    series = parse_series(payload)

    assert series.frequency_short == "D"
    assert series.source_last_updated.utcoffset() == timedelta(hours=-5)
    assert series.source_last_updated.astimezone(UTC).hour == 20


def test_year_windows_split_real_time_by_calendar_year() -> None:
    assert year_windows(date(2018, 12, 1), today=date(2020, 5, 1)) == [
        (date(2018, 12, 1), date(2018, 12, 31)),
        (date(2019, 1, 1), date(2019, 12, 31)),
        (date(2020, 1, 1), OPEN_END),
    ]


def test_year_windows_in_the_current_year_is_one_open_window() -> None:
    assert year_windows(date(2026, 9, 20), today=date(2026, 9, 27)) == [
        (date(2026, 9, 20), OPEN_END)
    ]


class PagedFred:
    """Serves `rows` in pages, reporting the total in "count" like FRED does."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.offsets: list[int] = []

    def get_series(self, series_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def get_observation_changes(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        offset, limit = args[4], args[5]
        self.offsets.append(offset)
        return {"count": len(self.rows), "observations": self.rows[offset : offset + limit]}


def test_extract_changes_reads_every_page() -> None:
    rows = [{"date": f"2024-12-2{d}", f"DGS10_2024122{d + 3}": "4.5"} for d in range(3)]
    fred = PagedFred(rows)

    changes = extract_changes(
        fred, "DGS10", date(2018, 12, 1), date(2024, 12, 1), OPEN_END, page_size=2
    )

    assert len(changes) == 3
    assert fred.offsets == [0, 2]
