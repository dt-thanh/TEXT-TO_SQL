"""Unit tests for the FRED watermark (publication date) and year-by-year loading."""

from datetime import date
from typing import Any

import pytest

from src.ingestion.fred import sync
from src.ingestion.fred.extractor import OPEN_END, FredObservation
from src.ingestion.fred.loader import OBSERVATION_SPEC, observation_row
from src.ingestion.fred.sync import (
    BACKFILL_START,
    INCREMENTAL_LOOKBACK,
    get_watermark,
    incremental_start,
    load_vintages,
)
from src.ingestion.merge_loader import LoadResult


def test_first_run_backfills_from_the_warm_up_month() -> None:
    assert incremental_start(None) == BACKFILL_START == date(2018, 12, 1)


def test_later_runs_reread_a_week_of_publications() -> None:
    assert incremental_start(date(2026, 9, 25)) == date(2026, 9, 25) - INCREMENTAL_LOOKBACK


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute(self, sql: str, params: dict[str, str]) -> "FakeCursor":
        self.calls.append((sql, params))
        return self

    def fetchone(self) -> tuple[date]:
        return (date(2026, 9, 25),)


class FakeConnection:
    def __init__(self) -> None:
        self.cur = FakeCursor()

    def cursor(self) -> FakeCursor:
        return self.cur


def test_watermark_is_newest_publication_date_not_observation_date() -> None:
    conn = FakeConnection()

    assert get_watermark(conn, "DGS10") == date(2026, 9, 25)
    sql, params = conn.cur.calls[0]
    assert "MAX(realtime_start)" in sql
    assert params == {"series_id": "DGS10"}


def test_observation_row_matches_the_table_columns() -> None:
    obs = FredObservation("DGS10", date(2024, 12, 20), date(2024, 12, 23), "4.52", None)

    row = dict(zip(OBSERVATION_SPEC.columns, observation_row(obs, "b-1", "now"), strict=True))

    assert row["realtime_start"] == date(2024, 12, 23)
    assert row["value_raw"] == "4.52"
    assert row["batch_id"] == "b-1"


def test_load_vintages_asks_one_calendar_year_of_publications_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows: list[tuple[date, date]] = []

    class FakeFred:
        def get_series(self, series_id: str) -> dict[str, Any]:
            return {"seriess": [{}]}

        def get_observation_changes(self, series_id, obs_start, rt_start, rt_end, offset, limit):  # noqa: ANN001, ANN201
            windows.append((rt_start, rt_end))
            return {"count": 1, "observations": [{"date": "2024-12-20", "DGS10_20241223": "4.52"}]}

    monkeypatch.setattr(sync, "extract_series", lambda source, series_id: None)
    monkeypatch.setattr(sync, "load_series", lambda conn, series, batch_id: None)
    monkeypatch.setattr(
        sync,
        "load_observations",
        lambda conn, obs, batch_id: LoadResult(batch_id, len(obs), len(obs), 0),
    )

    result = load_vintages(FakeFred(), None, "DGS10", date(2024, 6, 1), today=date(2026, 9, 27))

    assert windows == [
        (date(2024, 6, 1), date(2024, 12, 31)),
        (date(2025, 1, 1), date(2025, 12, 31)),
        (date(2026, 1, 1), OPEN_END),
    ]
    assert (result.windows, result.rows_received, result.rows_inserted) == (3, 3, 3)
