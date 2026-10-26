"""Refreshing the Binance catalog twice keeps it full (regression of 2026-10-26: the second refresh
deleted every pair). Live: Binance's exchangeInfo and the CONTROL schema."""

import pytest

from src.control.onboarding import refresh_catalog
from src.ingestion.binance.client import BinanceClient
from src.services.snowflake_client import ConnectionRunner, SnowflakeClient
from tests.integration.test_agent_permissions import agent_configured

pytestmark = pytest.mark.skipif(not agent_configured(), reason="Snowflake is not configured")


def test_a_second_refresh_keeps_every_pair() -> None:
    with BinanceClient() as binance, SnowflakeClient().connect() as conn:
        first = refresh_catalog(binance, conn)
        second = refresh_catalog(binance, conn)
        rows = ConnectionRunner(conn).execute(
            "SELECT COUNT(*) AS n FROM FINSIGHT.CONTROL.BINANCE_SYMBOL"
        )

    assert first > 100 and second > 100
    assert rows[0]["N"] == second
