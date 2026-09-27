"""Turn FRED payloads into typed series metadata and observation vintages.

An observation is a value for a date (observation_date) as published on a given day
(realtime_start). One date can have several vintages when FRED revises it; keeping all of
them is what lets later layers answer "what did an analyst know on day X?".
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from src.common.exceptions import SourceAPIError
from src.ingestion.fred.client import MAX_OBSERVATIONS_PER_REQUEST

# FRED's "no end" date for a vintage that is still current.
OPEN_END = date(9999, 12, 31)
MISSING_VALUE = "."


class FredSource(Protocol):
    """Anything that serves FRED payloads: FredClient in production, fakes in tests."""

    def get_series(self, series_id: str) -> dict[str, Any]: ...

    def get_observation_changes(
        self,
        series_id: str,
        observation_start: date,
        realtime_start: date,
        realtime_end: date,
        offset: int = 0,
        limit: int = MAX_OBSERVATIONS_PER_REQUEST,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FredSeries:
    """One row of RAW.RAW_FRED_SERIES."""

    series_id: str
    title: str
    frequency: str
    frequency_short: str
    units: str
    seasonal_adjustment: str
    observation_start: date
    observation_end: date
    source_last_updated: datetime


@dataclass(frozen=True)
class FredObservation:
    """One row of RAW.RAW_FRED_OBSERVATION: a value for a date, as published on a day."""

    series_id: str
    observation_date: date
    realtime_start: date
    value_raw: str
    value: Decimal | None


def parse_value(raw: str) -> Decimal | None:
    """FRED sends numbers as text and "." for "no value that day" (e.g. a market holiday)."""

    if raw == MISSING_VALUE:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation as err:
        raise SourceAPIError(f"Unexpected FRED value {raw!r}") from err


def parse_series(payload: dict[str, Any]) -> FredSeries:
    """Map the /series payload. last_updated looks like '2026-09-25 15:16:33-05' (US Central)."""

    try:
        item = payload["seriess"][0]
        return FredSeries(
            series_id=item["id"],
            title=item["title"],
            frequency=item["frequency"],
            frequency_short=item["frequency_short"],
            units=item["units"],
            seasonal_adjustment=item["seasonal_adjustment"],
            observation_start=date.fromisoformat(item["observation_start"]),
            observation_end=date.fromisoformat(item["observation_end"]),
            source_last_updated=datetime.fromisoformat(item["last_updated"]),
        )
    except (KeyError, IndexError, ValueError) as err:
        raise SourceAPIError(f"Unexpected FRED series payload: {payload!r:.300}") from err


def parse_changes(series_id: str, rows: list[dict[str, Any]]) -> list[FredObservation]:
    """Unpack output_type=3 rows into one observation per (date, vintage).

    A row looks like {"date": "2024-08-01", "CPIAUCSL_20240911": "314.121",
    "CPIAUCSL_20250212": "314.131"}: the key suffix is the publication date.
    """

    observations = []
    for row in rows:
        try:
            observation_date = date.fromisoformat(row["date"])
            for key, raw in row.items():
                if key == "date":
                    continue
                prefix, vintage = key.rsplit("_", 1)
                if prefix != series_id:
                    raise ValueError(f"column {key} does not belong to {series_id}")
                observations.append(
                    FredObservation(
                        series_id=series_id,
                        observation_date=observation_date,
                        realtime_start=datetime.strptime(vintage, "%Y%m%d").date(),
                        value_raw=raw,
                        value=parse_value(raw),
                    )
                )
        except (KeyError, ValueError) as err:
            raise SourceAPIError(f"Unexpected FRED observation row {row!r}: {err}") from err
    return observations


def year_windows(start: date, today: date) -> list[tuple[date, date]]:
    """Split real time from `start` to now into calendar years; the last window is open-ended.

    FRED refuses a request that spans more than 2000 vintage dates, and a daily series gains
    about 250 per year, so one year per request stays far below the limit.
    """

    windows = []
    cursor = start
    while cursor.year < today.year:
        year_end = date(cursor.year, 12, 31)
        windows.append((cursor, year_end))
        cursor = year_end + timedelta(days=1)
    windows.append((cursor, OPEN_END))
    return windows


def extract_series(source: FredSource, series_id: str) -> FredSeries:
    return parse_series(source.get_series(series_id))


def extract_changes(
    source: FredSource,
    series_id: str,
    observation_start: date,
    realtime_start: date,
    realtime_end: date,
    page_size: int = MAX_OBSERVATIONS_PER_REQUEST,
) -> list[FredObservation]:
    """Every value first published or revised in [realtime_start, realtime_end], all pages."""

    observations: list[FredObservation] = []
    offset = 0
    while True:
        payload = source.get_observation_changes(
            series_id, observation_start, realtime_start, realtime_end, offset, page_size
        )
        rows = payload.get("observations", [])
        observations.extend(parse_changes(series_id, rows))
        offset += len(rows)
        if not rows or offset >= int(payload.get("count", 0)):
            return observations
