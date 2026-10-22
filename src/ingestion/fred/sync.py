"""Keep RAW FRED tables current: backfill vintages once, then load only newly published values.

The watermark is the newest realtime_start (publication date) already in RAW, not the newest
observation_date: "new information" for FRED means "published since last time", and a
revision of an old observation is new information too.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.exceptions import WarehouseError
from src.ingestion.fred.extractor import (
    OPEN_END,
    FredSource,
    extract_changes,
    extract_series,
    year_windows,
)
from src.ingestion.fred.loader import OBSERVATION_TABLE, load_observations, load_series
from src.ingestion.merge_loader import new_batch_id

logger = logging.getLogger(__name__)

MVP_SERIES = ("DFF", "DGS10", "CPIAUCSL")
# One month before the Binance backfill start, so that 2019-01-01 already has a value that
# had been published by then (point-in-time lookups need the last value known on each day).
BACKFILL_START = date(2018, 12, 1)
# Re-read a week of publications on every incremental run; MERGE makes the overlap harmless.
INCREMENTAL_LOOKBACK = timedelta(days=7)
# A monthly series needs a year more: the year-over-year change of a 2019 month needs 2018, and a
# monthly value is published only once, so it must be in the first window of the backfill.
SERIES_BACKFILL_START = {"CPIAUCSL": date(2017, 1, 1)}


def backfill_start(series_id: str) -> date:
    """First observation date (and first publication date) loaded for this series."""

    return SERIES_BACKFILL_START.get(series_id, BACKFILL_START)


@dataclass(frozen=True)
class FredSyncResult:
    series_id: str
    realtime_start: date
    windows: int
    rows_received: int
    rows_inserted: int
    rows_updated: int


def incremental_start(watermark: date | None, series_id: str = "") -> date:
    """First publication date to ask for: all of history if RAW has nothing for the series."""

    if watermark is None:
        return backfill_start(series_id)
    return watermark - INCREMENTAL_LOOKBACK


def get_watermark(conn: Any, series_id: str, table: str = OBSERVATION_TABLE) -> date | None:
    """Newest publication date (realtime_start) already in RAW for this series, or None."""

    sql = f"SELECT MAX(realtime_start) FROM {table} WHERE series_id = %(series_id)s"
    try:
        with conn.cursor() as cur:
            return cur.execute(sql, {"series_id": series_id}).fetchone()[0]
    except SnowflakeDriverError as err:
        message = f"Reading the {series_id} watermark from {table} failed: {err}"
        raise WarehouseError(message) from err


def load_vintages(
    source: FredSource,
    conn: Any,
    series_id: str,
    realtime_start: date,
    today: date | None = None,
) -> FredSyncResult:
    """Refresh series metadata, then load every value published from `realtime_start` on,
    one calendar year of publications per request."""

    today = today or datetime.now(UTC).date()
    load_series(conn, extract_series(source, series_id), new_batch_id())

    windows = year_windows(realtime_start, today)
    received = inserted = updated = 0
    for window_start, window_end in windows:
        observation_start = backfill_start(series_id)
        changes = extract_changes(source, series_id, observation_start, window_start, window_end)
        result = load_observations(conn, changes, new_batch_id())
        received += result.rows_received
        inserted += result.rows_inserted
        updated += result.rows_updated
        logger.info(
            "%s published [%s, %s]: %d received, %d inserted, %d updated",
            series_id,
            window_start.isoformat(),
            "open" if window_end == OPEN_END else window_end.isoformat(),
            result.rows_received,
            result.rows_inserted,
            result.rows_updated,
        )

    summary = FredSyncResult(series_id, realtime_start, len(windows), received, inserted, updated)
    logger.info(
        "%s done: %d window(s), %d received, %d inserted, %d updated",
        series_id,
        summary.windows,
        received,
        inserted,
        updated,
    )
    return summary


def sync_series(
    source: FredSource, conn: Any, series_id: str, today: date | None = None
) -> FredSyncResult:
    """Incremental run for one series: from watermark minus lookback, or the backfill start."""

    watermark = get_watermark(conn, series_id)
    start = incremental_start(watermark, series_id)
    logger.info(
        "%s watermark=%s → loading publications from %s",
        series_id,
        watermark.isoformat() if watermark else "none (first run, full backfill)",
        start.isoformat(),
    )
    return load_vintages(source, conn, series_id, start, today)
