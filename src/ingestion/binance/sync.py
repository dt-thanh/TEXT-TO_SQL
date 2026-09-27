"""Keep RAW.RAW_BINANCE_KLINE current: backfill history once, then load only what is new.

Two ways to choose the window:
- incremental: continue from the watermark (newest open_time already in RAW), minus a lookback;
- explicit: a caller-given [start, end), used for backfills and repairs.
Either way the window is loaded one UTC month at a time, and each month commits on its own.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.exceptions import WarehouseError
from src.ingestion.binance.extractor import KlineSource, extract_klines
from src.ingestion.binance.loader import RAW_TABLE, load_klines, new_batch_id

logger = logging.getLogger(__name__)

MVP_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT")
BACKFILL_START = datetime(2019, 1, 1, tzinfo=UTC)
# Every incremental run re-reads the last day. MERGE makes the overlap duplicate-free, and it
# picks up a candle that Binance corrected after we first loaded it (late-arriving data).
INCREMENTAL_LOOKBACK = timedelta(days=1)


@dataclass(frozen=True)
class SyncResult:
    """Totals for one symbol over one [start, end) window."""

    symbol: str
    start: datetime
    end: datetime
    months: int
    rows_received: int
    rows_inserted: int
    rows_updated: int


def month_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Split [start, end) at UTC month boundaries.

    Each piece is extracted, merged and committed separately, so a crash in month 50
    keeps months 1-49 and a re-run only has to redo the rest.
    """

    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    windows = []
    cursor, end = start.astimezone(UTC), end.astimezone(UTC)
    while cursor < end:
        month_start = cursor.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (month_start + timedelta(days=32)).replace(day=1)
        if next_month <= cursor:
            raise ValueError(f"month split stopped advancing at {cursor}")
        windows.append((cursor, min(next_month, end)))
        cursor = next_month
    return windows


def incremental_start(watermark: datetime | None) -> datetime:
    """Where an incremental run starts: all of history if RAW has nothing for the symbol yet."""

    if watermark is None:
        return BACKFILL_START
    return watermark - INCREMENTAL_LOOKBACK


def get_watermark(conn: Any, symbol: str, interval: str, table: str = RAW_TABLE) -> datetime | None:
    """Open time of the newest candle already in `table` for this symbol, or None if none."""

    sql = (
        f"SELECT MAX(open_time) FROM {table} "
        "WHERE symbol = %(symbol)s AND interval_code = %(interval)s"
    )
    try:
        with conn.cursor() as cur:
            return cur.execute(sql, {"symbol": symbol, "interval": interval}).fetchone()[0]
    except SnowflakeDriverError as err:
        raise WarehouseError(f"Reading the {symbol} watermark from {table} failed: {err}") from err


def load_window(
    source: KlineSource,
    conn: Any,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
) -> SyncResult:
    """Extract and MERGE every closed candle in [start, end), one month at a time."""

    now = now or datetime.now(UTC)
    windows = month_windows(start, end)
    received = inserted = updated = 0
    for window_start, window_end in windows:
        klines = extract_klines(source, symbol, interval, window_start, window_end, now)
        result = load_klines(conn, klines, new_batch_id())
        received += result.rows_received
        inserted += result.rows_inserted
        updated += result.rows_updated
        logger.info(
            "%s %s [%s, %s): %d received, %d inserted, %d updated",
            symbol,
            interval,
            window_start.isoformat(),
            window_end.isoformat(),
            result.rows_received,
            result.rows_inserted,
            result.rows_updated,
        )

    summary = SyncResult(symbol, start, end, len(windows), received, inserted, updated)
    logger.info(
        "%s done: %d month(s), %d received, %d inserted, %d updated",
        symbol,
        summary.months,
        received,
        inserted,
        updated,
    )
    return summary


def sync_symbol(
    source: KlineSource,
    conn: Any,
    symbol: str,
    interval: str = "1h",
    now: datetime | None = None,
) -> SyncResult:
    """Incremental run for one symbol: from the watermark (or the backfill start) up to now."""

    now = now or datetime.now(UTC)
    watermark = get_watermark(conn, symbol, interval)
    start = incremental_start(watermark)
    logger.info(
        "%s watermark=%s → loading from %s",
        symbol,
        watermark.isoformat() if watermark else "none (first run, full backfill)",
        start.isoformat(),
    )
    return load_window(source, conn, symbol, interval, start, now, now)
