"""Load extracted Binance klines into RAW.RAW_BINANCE_KLINE, idempotently.

Flow: rows → temporary stage table (same session) → one MERGE keyed on the grain.
Re-loading the same candles changes nothing; a corrected candle updates its one row.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.exceptions import WarehouseError
from src.ingestion.binance.extractor import Kline

logger = logging.getLogger(__name__)

RAW_TABLE = "FINSIGHT.RAW.RAW_BINANCE_KLINE"
STAGE_TABLE = "FINSIGHT.RAW.TMP_BINANCE_KLINE_LOAD"
SOURCE_NAME = "binance_api:/api/v3/klines"
INSERT_BATCH_ROWS = 2000

KEY_COLUMNS = ("symbol", "interval_code", "open_time")
KLINE_COLUMNS = (
    *KEY_COLUMNS,
    "close_time",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "base_volume",
    "quote_volume",
    "trade_count",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
)
VALUE_COLUMNS = tuple(column for column in KLINE_COLUMNS if column not in KEY_COLUMNS)
METADATA_COLUMNS = ("source_file", "ingested_at", "batch_id")
ALL_COLUMNS = KLINE_COLUMNS + METADATA_COLUMNS


@dataclass(frozen=True)
class LoadResult:
    """What one load did to the target table."""

    batch_id: str
    rows_received: int
    rows_inserted: int
    rows_updated: int


def new_batch_id() -> str:
    """Readable, unique id for one load run, e.g. 20260927T101500Z-1a2b3c4d."""

    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"


def build_merge_sql(target_table: str, stage_table: str) -> str:
    """MERGE the stage table into the target on the grain (symbol, interval, open_time).

    Unchanged candles are left alone, so a re-run reports 0 inserted and 0 updated.
    QUALIFY keeps one row per key in case a batch ever contains the same candle twice.
    """

    columns = ", ".join(ALL_COLUMNS)
    key_match = " AND ".join(f"target.{c} = source.{c}" for c in KEY_COLUMNS)
    changed = " OR ".join(f"target.{c} IS DISTINCT FROM source.{c}" for c in VALUE_COLUMNS)
    updates = ", ".join(f"{c} = source.{c}" for c in VALUE_COLUMNS + METADATA_COLUMNS)
    source_values = ", ".join(f"source.{c}" for c in ALL_COLUMNS)
    return f"""
MERGE INTO {target_table} AS target
USING (
    SELECT {columns}
    FROM {stage_table}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY {", ".join(KEY_COLUMNS)} ORDER BY close_time DESC
    ) = 1
) AS source
ON {key_match}
WHEN MATCHED AND ({changed}) THEN UPDATE SET {updates}
WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({source_values})
"""


def to_row(kline: Kline, batch_id: str, ingested_at: datetime) -> tuple[Any, ...]:
    """One stage-table row, in ALL_COLUMNS order."""

    return (
        *(getattr(kline, column) for column in KLINE_COLUMNS),
        SOURCE_NAME,
        ingested_at,
        batch_id,
    )


def load_klines(
    conn: Any,
    klines: Sequence[Kline],
    batch_id: str,
    ingested_at: datetime | None = None,
    target_table: str = RAW_TABLE,
    batch_rows: int = INSERT_BATCH_ROWS,
) -> LoadResult:
    """Upsert klines into `target_table` through a temporary stage table.

    `conn` is an open Snowflake connection. The stage table is TEMPORARY: only this
    session sees it and it disappears when the connection closes. If anything fails
    before the MERGE, the target table is untouched.
    """

    if not klines:
        return LoadResult(batch_id, 0, 0, 0)

    ingested_at = ingested_at or datetime.now(UTC)
    rows = [to_row(kline, batch_id, ingested_at) for kline in klines]
    placeholders = ", ".join(["%s"] * len(ALL_COLUMNS))
    insert_sql = f"INSERT INTO {STAGE_TABLE} ({', '.join(ALL_COLUMNS)}) VALUES ({placeholders})"

    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {STAGE_TABLE} LIKE {target_table}")
            for start in range(0, len(rows), batch_rows):
                cur.executemany(insert_sql, rows[start : start + batch_rows])
            cur.execute(build_merge_sql(target_table, STAGE_TABLE))
            inserted, updated = cur.fetchone()
    except SnowflakeDriverError as err:
        raise WarehouseError(f"Loading batch {batch_id} into {target_table} failed: {err}") from err

    result = LoadResult(batch_id, len(rows), inserted, updated)
    logger.info(
        "Loaded batch %s into %s: %d received, %d inserted, %d updated",
        batch_id,
        target_table,
        result.rows_received,
        result.rows_inserted,
        result.rows_updated,
    )
    return result
