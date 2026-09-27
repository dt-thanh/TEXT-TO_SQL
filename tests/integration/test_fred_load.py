"""Integration test: loading FRED vintages on real Snowflake, against a TEMPORARY table."""

from datetime import date
from decimal import Decimal

import pytest

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.ingestion.fred.extractor import FredObservation
from src.ingestion.fred.loader import OBSERVATION_TABLE, load_observations
from src.services.snowflake_client import SnowflakeClient

TARGET = "FINSIGHT.RAW.TMP_TEST_FRED_TARGET"


def snowflake_configured() -> bool:
    try:
        get_settings().require_snowflake()
    except ConfigError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not snowflake_configured(), reason="Snowflake is not configured in .env"
)


def cpi(published: date, value: str) -> FredObservation:
    return FredObservation("CPIAUCSL", date(2024, 8, 1), published, value, Decimal(value))


def test_a_revision_adds_a_row_and_keeps_the_first_release() -> None:
    first_two = [cpi(date(2024, 9, 11), "314.121"), cpi(date(2025, 2, 12), "314.131")]
    revision = [cpi(date(2026, 2, 13), "314.062")]

    with SnowflakeClient().connect() as conn:
        conn.cursor().execute(f"CREATE TEMPORARY TABLE {TARGET} LIKE {OBSERVATION_TABLE}")
        first = load_observations(conn, first_two, "batch-1", target_table=TARGET)
        rerun = load_observations(conn, first_two, "batch-2", target_table=TARGET)
        revised = load_observations(conn, revision, "batch-3", target_table=TARGET)
        rows = conn.cursor().execute(
            f"SELECT realtime_start, value FROM {TARGET} ORDER BY realtime_start"
        ).fetchall()

    assert (first.rows_inserted, first.rows_updated) == (2, 0)
    assert (rerun.rows_inserted, rerun.rows_updated) == (0, 0)
    assert (revised.rows_inserted, revised.rows_updated) == (1, 0)
    assert rows == [
        (date(2024, 9, 11), Decimal("314.1210000000")),
        (date(2025, 2, 12), Decimal("314.1310000000")),
        (date(2026, 2, 13), Decimal("314.0620000000")),
    ]
