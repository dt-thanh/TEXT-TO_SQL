"""Unit tests for the RAW loader. A fake connection records the SQL instead of running it."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from snowflake.connector.errors import ProgrammingError

from src.common.exceptions import WarehouseError
from src.ingestion.binance.extractor import Kline
from src.ingestion.binance.loader import (
    ALL_COLUMNS,
    RAW_TABLE,
    SOURCE_NAME,
    STAGE_TABLE,
    build_merge_sql,
    load_klines,
)

T0 = datetime(2024, 1, 1, tzinfo=UTC)
INGESTED_AT = datetime(2026, 9, 27, 10, 0, tzinfo=UTC)


def make_kline(hour: int) -> Kline:
    open_time = T0 + timedelta(hours=hour)
    return Kline(
        symbol="BTCUSDT",
        interval_code="1h",
        open_time=open_time,
        close_time=open_time + timedelta(hours=1, milliseconds=-1),
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105"),
        base_volume=Decimal("1.5"),
        quote_volume=Decimal("157.5"),
        trade_count=10,
        taker_buy_base_volume=Decimal("0.5"),
        taker_buy_quote_volume=Decimal("52.5"),
    )


class FakeCursor:
    def __init__(self, merge_result: tuple[int, int], error: Exception | None = None) -> None:
        self.merge_result = merge_result
        self.error = error
        self.statements: list[str] = []
        self.batches: list[list[tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute(self, sql: str) -> None:
        self.statements.append(sql)
        if self.error and sql.lstrip().startswith("MERGE"):
            raise self.error

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        self.statements.append(sql)
        self.batches.append(rows)

    def fetchone(self) -> tuple[int, int]:
        return self.merge_result


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def load(cursor: FakeCursor, hours: int, batch_rows: int = 2000) -> Any:
    klines = [make_kline(h) for h in range(hours)]
    return load_klines(
        FakeConnection(cursor), klines, "batch-1", INGESTED_AT, batch_rows=batch_rows
    )


def test_stages_rows_then_merges_into_raw() -> None:
    cursor = FakeCursor(merge_result=(3, 0))

    result = load(cursor, hours=3)

    create, insert, merge = cursor.statements
    assert create == f"CREATE OR REPLACE TEMPORARY TABLE {STAGE_TABLE} LIKE {RAW_TABLE}"
    assert insert.startswith(f"INSERT INTO {STAGE_TABLE}")
    assert merge.lstrip().startswith(f"MERGE INTO {RAW_TABLE}")
    assert (result.rows_received, result.rows_inserted, result.rows_updated) == (3, 3, 0)


def test_rows_carry_candle_values_and_load_metadata() -> None:
    cursor = FakeCursor(merge_result=(1, 0))

    load(cursor, hours=1)

    row = dict(zip(ALL_COLUMNS, cursor.batches[0][0], strict=True))
    assert row["symbol"] == "BTCUSDT"
    assert row["open_time"] == T0
    assert row["close_price"] == Decimal("105")
    assert row["source_file"] == SOURCE_NAME
    assert row["ingested_at"] == INGESTED_AT
    assert row["batch_id"] == "batch-1"


def test_large_loads_are_sent_in_batches() -> None:
    cursor = FakeCursor(merge_result=(5, 0))

    load(cursor, hours=5, batch_rows=2)

    assert [len(batch) for batch in cursor.batches] == [2, 2, 1]


def test_nothing_to_load_sends_no_sql() -> None:
    cursor = FakeCursor(merge_result=(0, 0))

    result = load_klines(FakeConnection(cursor), [], "batch-1")

    assert cursor.statements == []
    assert result.rows_received == 0


def test_merge_matches_on_the_grain_and_skips_unchanged_rows() -> None:
    sql = build_merge_sql(RAW_TABLE, STAGE_TABLE)

    assert (
        "ON target.symbol = source.symbol AND target.interval_code = source.interval_code "
        "AND target.open_time = source.open_time"
    ) in sql
    assert "target.close_price IS DISTINCT FROM source.close_price" in sql
    assert "QUALIFY ROW_NUMBER()" in sql


def test_driver_errors_become_warehouse_errors() -> None:
    cursor = FakeCursor(merge_result=(0, 0), error=ProgrammingError("SQL compilation error"))

    with pytest.raises(WarehouseError, match="batch-1"):
        load(cursor, hours=1)
