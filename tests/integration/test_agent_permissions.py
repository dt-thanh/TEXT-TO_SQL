"""Integration test: the agent's Snowflake user can read MART and nothing else.

This is the database half of "the LLM must never decide authorization" (spec §23): even SQL
that slips past every check in our code cannot touch other layers or change data.
Needs infra/snowflake/02_agent_user.sql run and the agent key registered.
"""

import pytest

from src.agents.text_to_sql import agent_warehouse
from src.common.config import get_settings
from src.common.exceptions import ConfigError, WarehouseError


def agent_configured() -> bool:
    try:
        get_settings().for_agent().require_snowflake()
    except ConfigError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not agent_configured(), reason="Agent Snowflake user is not configured in .env"
)


def test_agent_can_read_mart() -> None:
    rows = agent_warehouse().execute(
        "SELECT CURRENT_ROLE() AS role_name, COUNT(*) AS n FROM FINSIGHT.MART.MART_ASSET_DAILY"
    )

    assert rows[0]["ROLE_NAME"] == "FINSIGHT_AGENT"
    assert rows[0]["N"] > 0


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM FINSIGHT.CORE.FCT_CRYPTO_KLINE_1H",
        "SELECT COUNT(*) FROM FINSIGHT.RAW.RAW_BINANCE_KLINE",
        "DELETE FROM FINSIGHT.MART.MART_ASSET_DAILY",
        "CREATE TABLE FINSIGHT.MART.AGENT_WAS_HERE (x INT)",
    ],
)
def test_agent_cannot_leave_mart_or_change_data(sql: str) -> None:
    with pytest.raises(WarehouseError):
        agent_warehouse().execute(sql)
