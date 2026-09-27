"""Load extracted Binance klines into RAW.RAW_BINANCE_KLINE, idempotently.

This file only describes the Binance table (grain, value columns, metadata) and turns a
Kline into a row. The stage-table + MERGE mechanics live in src/ingestion/merge_loader.py.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from src.ingestion.binance.extractor import Kline
from src.ingestion.merge_loader import (
    INSERT_BATCH_ROWS,
    LoadResult,
    TableSpec,
    merge_rows,
    new_batch_id,
)
from src.ingestion.merge_loader import build_merge_sql as build_spec_merge_sql

__all__ = ["LoadResult", "load_klines", "new_batch_id"]

RAW_TABLE = "FINSIGHT.RAW.RAW_BINANCE_KLINE"
STAGE_TABLE = "FINSIGHT.RAW.TMP_BINANCE_KLINE_LOAD"
SOURCE_NAME = "binance_api:/api/v3/klines"

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

KLINE_SPEC = TableSpec(
    target_table=RAW_TABLE,
    stage_table=STAGE_TABLE,
    key_columns=KEY_COLUMNS,
    value_columns=VALUE_COLUMNS,
    metadata_columns=METADATA_COLUMNS,
    dedupe_order_by="close_time DESC",
)


def build_merge_sql(target_table: str, stage_table: str) -> str:
    """The MERGE used for klines: matches on (symbol, interval_code, open_time)."""

    return build_spec_merge_sql(replace(KLINE_SPEC, stage_table=stage_table), target_table)


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
    """Upsert klines into `target_table` (RAW by default) in one MERGE."""

    ingested_at = ingested_at or datetime.now(UTC)
    rows = [to_row(kline, batch_id, ingested_at) for kline in klines]
    return merge_rows(conn, KLINE_SPEC, rows, batch_id, target_table, batch_rows)
