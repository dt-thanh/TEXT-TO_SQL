"""Integration test: the agent's Snowflake user can read MART and nothing else.

This is the database half of "the LLM must never decide authorization" (spec §23): even SQL
that slips past every check in our code cannot touch other layers or change data.
Needs infra/snowflake/02_agent_user.sql run and the agent key registered.
"""

import pytest

from src.agents.text_to_sql import agent_warehouse
from src.common.config import get_settings
from src.common.exceptions import ConfigError, WarehouseError
from src.services.snowflake_client import SnowflakeClient


def agent_configured() -> bool:
    try:
        get_settings().for_agent().require_snowflake()
    except ConfigError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not agent_configured(), reason="Agent Snowflake user is not configured in .env"
)

# What Snowflake says when a role lacks a privilege. A failed CONNECTION says something else
# ("JWT token is invalid"), so it can no longer make the "cannot" tests pass by accident.
PERMISSION_DENIED = "does not exist or not authorized|Insufficient privileges"


@pytest.fixture(scope="module")
def agent() -> SnowflakeClient:
    """The agent's connection, proven to work BEFORE any permission is tested.

    Without this check, every "agent cannot ..." test below would also pass when the agent
    cannot even log in, because a failed login raises WarehouseError too.
    """

    client = agent_warehouse()
    try:
        client.execute("SELECT 1")
    except WarehouseError as err:
        pytest.fail(
            "The agent user cannot log in. Run infra/snowflake/02_agent_user.sql in Snowsight "
            f"and set its RSA_PUBLIC_KEY from ~/.snowflake/finsight_agent_key.pub. ({err})"
        )
    return client


def test_agent_can_read_mart(agent: SnowflakeClient) -> None:
    rows = agent.execute(
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
def test_agent_cannot_leave_mart_or_change_data(agent: SnowflakeClient, sql: str) -> None:
    with pytest.raises(WarehouseError, match=PERMISSION_DENIED):
        agent.execute(sql)
