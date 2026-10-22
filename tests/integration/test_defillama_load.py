"""Integration tests: DefiLlama's live API and the versioned TVL load on real Snowflake.

The load test writes to a TEMPORARY table shaped like RAW, so RAW itself is never touched.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.ingestion.defillama.client import DefiLlamaClient
from src.ingestion.defillama.extractor import ChainTvl, extract_chain_tvl
from src.ingestion.defillama.loader import RAW_TABLE, load_chain_tvl
from src.services.snowflake_client import SnowflakeClient

TARGET = "FINSIGHT.RAW.TMP_TEST_DEFILLAMA_TARGET"
DAY1, DAY2 = date(2026, 10, 20), date(2026, 10, 21)


def snowflake_configured() -> bool:
    try:
        get_settings().require_snowflake()
    except ConfigError:
        return False
    return True


def tvl(day: date, usd: str) -> ChainTvl:
    return ChainTvl("Ethereum", day, Decimal(usd))


def test_the_live_series_has_finished_days_only_and_starts_at_the_first_tracked_day() -> None:
    today = date.today()
    with DefiLlamaClient() as client:
        points = extract_chain_tvl(client, "Ethereum", today)

    assert points[0].tvl_date == date(2018, 2, 12)
    assert points[-1].tvl_date < today
    assert points[-1].tvl_date >= today - timedelta(days=3)


@pytest.mark.skipif(not snowflake_configured(), reason="Snowflake is not configured in .env")
def test_a_revision_is_a_new_version_and_a_same_day_rerun_changes_nothing() -> None:
    fetched_first, fetched_next = date(2026, 10, 21), date(2026, 10, 22)
    first_fetch = [tvl(DAY1, "49342841750")]
    next_fetch = [tvl(DAY1, "49342841750"), tvl(DAY2, "50277990421")]
    revised_fetch = [tvl(DAY1, "49342841750"), tvl(DAY2, "50224842407")]

    with SnowflakeClient().connect() as conn:
        conn.cursor().execute(f"CREATE TEMPORARY TABLE {TARGET} LIKE {RAW_TABLE}")
        backfill = load_chain_tvl(conn, first_fetch, fetched_first, True, "b1", target_table=TARGET)
        daily = load_chain_tvl(conn, next_fetch, fetched_next, False, "b2", target_table=TARGET)
        rerun = load_chain_tvl(conn, next_fetch, fetched_next, False, "b3", target_table=TARGET)
        moved = load_chain_tvl(conn, revised_fetch, fetched_next, False, "b4", target_table=TARGET)
        later = load_chain_tvl(
            conn, revised_fetch, fetched_next + timedelta(days=1), False, "b5", target_table=TARGET
        )
        rows = conn.cursor().execute(
            f"SELECT tvl_date, fetched_date, tvl_usd, is_backfill FROM {TARGET} ORDER BY 1, 2"
        ).fetchall()

    assert (backfill.rows_inserted, backfill.rows_updated) == (1, 0)
    assert (daily.rows_inserted, daily.rows_updated) == (1, 0)  # DAY1 unchanged: no new version
    assert (rerun.rows_inserted, rerun.rows_updated) == (0, 0)  # same day, same values
    assert (moved.rows_inserted, moved.rows_updated) == (0, 1)  # same day, DefiLlama moved again
    assert (later.rows_inserted, later.rows_updated) == (0, 0)  # next day, nothing changed
    assert rows == [
        (DAY1, fetched_first, Decimal("49342841750.00"), True),
        (DAY2, fetched_next, Decimal("50224842407.00"), False),
    ]
