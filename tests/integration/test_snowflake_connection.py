"""Integration tests against the real Snowflake account configured in .env."""

import pytest

from src.common.config import get_settings
from src.common.exceptions import ConfigError
from src.services.snowflake_client import SnowflakeClient


def snowflake_configured() -> bool:
    try:
        get_settings().require_snowflake()
    except ConfigError:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not snowflake_configured(), reason="Snowflake is not configured in .env"
)


def test_connects_with_engineer_role() -> None:
    rows = SnowflakeClient().execute(
        "SELECT CURRENT_ROLE() AS role_name, CURRENT_DATABASE() AS database_name"
    )

    assert rows == [{"ROLE_NAME": "FINSIGHT_ENGINEER", "DATABASE_NAME": "FINSIGHT"}]


def test_all_layer_schemas_exist() -> None:
    rows = SnowflakeClient().execute("SELECT schema_name FROM FINSIGHT.INFORMATION_SCHEMA.SCHEMATA")

    assert {"RAW", "STAGING", "CORE", "MART"} <= {row["SCHEMA_NAME"] for row in rows}
