"""Integration test: the watermark query on real Snowflake, against a TEMPORARY table."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.ingestion.binance.extractor import Kline
from src.ingestion.binance.loader import RAW_TABLE, load_klines
from src.ingestion.binance.sync import get_watermark
from src.services.snowflake_client import SnowflakeClient

TARGET = "FINSIGHT.RAW.TMP_TEST_WATERMARK"
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
    one = Decimal("1")
    return Kline(
        "BTCUSDT", "1h", open_time, open_time + timedelta(hours=1, milliseconds=-1),
        one, one, one, one, one, one, 1, one, one,
    )  # fmt: skip


def test_watermark_is_newest_open_time_per_symbol() -> None:
    with SnowflakeClient().connect() as conn:
        conn.cursor().execute(f"CREATE TEMPORARY TABLE {TARGET} LIKE {RAW_TABLE}")
        empty = get_watermark(conn, "BTCUSDT", "1h", table=TARGET)
        load_klines(conn, [make_kline(h) for h in range(3)], "batch-1", target_table=TARGET)
        loaded = get_watermark(conn, "BTCUSDT", "1h", table=TARGET)
        other_symbol = get_watermark(conn, "ETHUSDT", "1h", table=TARGET)

    assert empty is None
    assert loaded == T0 + timedelta(hours=2)
    assert other_symbol is None
