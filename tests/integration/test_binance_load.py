"""Integration test: the loader's MERGE is idempotent on real Snowflake.

Uses a TEMPORARY target table shaped like RAW, so RAW itself is never touched.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.ingestion.binance.extractor import Kline
from src.ingestion.binance.loader import RAW_TABLE, load_klines
from src.services.snowflake_client import SnowflakeClient

TARGET = "FINSIGHT.RAW.TMP_TEST_KLINE_TARGET"
T0 = datetime(2024, 1, 1, tzinfo=UTC)


def snowflake_configured() -> bool:
    try:
        get_settings().require_snowflake()
    except ConfigError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not snowflake_configured(), reason="Snowflake is not configured in .env"
)


def make_kline(hour: int) -> Kline:
    open_time = T0 + timedelta(hours=hour)
    return Kline(
        symbol="BTCUSDT",
        interval_code="1h",
        open_time=open_time,
        close_time=open_time + timedelta(hours=1, milliseconds=-1),
        open_price=Decimal("100.12345678"),
        high_price=Decimal("110"),
        low_price=Decimal("90"),
        close_price=Decimal("105.5"),
        base_volume=Decimal("1.5"),
        quote_volume=Decimal("157.5"),
        trade_count=10,
        taker_buy_base_volume=Decimal("0.5"),
        taker_buy_quote_volume=Decimal("52.5"),
    )


def test_reloading_changes_nothing_and_corrections_update_one_row() -> None:
    klines = [make_kline(h) for h in range(3)]
    corrected = replace(klines[0], close_price=Decimal("106"))

    with SnowflakeClient().connect() as conn:
        conn.cursor().execute(f"CREATE TEMPORARY TABLE {TARGET} LIKE {RAW_TABLE}")
        first = load_klines(conn, klines, "batch-1", target_table=TARGET)
        rerun = load_klines(conn, klines, "batch-2", target_table=TARGET)
        fix = load_klines(conn, [corrected], "batch-3", target_table=TARGET)
        rows = conn.cursor().execute(
            f"SELECT open_time, close_price, open_price FROM {TARGET} ORDER BY open_time"
        ).fetchall()

    assert (first.rows_inserted, first.rows_updated) == (3, 0)
    assert (rerun.rows_inserted, rerun.rows_updated) == (0, 0)
    assert (fix.rows_inserted, fix.rows_updated) == (0, 1)
    assert [open_time for open_time, _, _ in rows] == [k.open_time for k in klines]
    assert [close for _, close, _ in rows] == [Decimal("106"), Decimal("105.5"), Decimal("105.5")]
    assert rows[0][2] == Decimal("100.12345678")
