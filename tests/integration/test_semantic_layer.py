"""Integration test: the semantic layer agrees with the real data in Snowflake.

A definition the data contradicts is worse than none: the model follows it confidently. So:
- the assets in glossary.yml are exactly the symbols in MART (a new asset must be added there);
- the macro series named in glossary.yml are real MART columns;
- every verified query passes the SQL guard and returns rows. No LLM call.
"""

from typing import Any

import pytest

from src.agents.text_to_sql import agent_warehouse
from src.agents.tools.schema_tools import SCHEMA_SQL, get_schema_context
from src.semantic.layer import load_semantic_layer
from src.services.snowflake_client import SnowflakeClient
from src.services.sql_guard import SQLGuard
from tests.integration.test_agent_permissions import agent_configured

pytestmark = pytest.mark.skipif(
    not agent_configured(), reason="Agent Snowflake user is not configured in .env"
)

LAYER = load_semantic_layer()


@pytest.fixture(scope="module")
def warehouse() -> SnowflakeClient:
    return agent_warehouse()


def test_glossary_assets_are_exactly_the_symbols_in_mart(warehouse: SnowflakeClient) -> None:
    rows = warehouse.execute("SELECT DISTINCT symbol FROM FINSIGHT.MART.MART_ASSET_DAILY")

    assert {row["SYMBOL"] for row in rows} == {a.symbol for a in LAYER.coverage.assets}


def test_glossary_macro_series_are_real_mart_columns(warehouse: SnowflakeClient) -> None:
    rows = warehouse.execute(SCHEMA_SQL, {"schema": "MART"})
    macro_columns = {r["COLUMN_NAME"] for r in rows if r["TABLE_NAME"] == "MART_MACRO_DAILY"}

    assert {s.column.upper() for s in LAYER.coverage.macro_series} <= macro_columns


@pytest.mark.parametrize("example", LAYER.verified_queries, ids=lambda q: q.id)
def test_verified_query_passes_the_guard_and_returns_rows(
    example: Any, warehouse: SnowflakeClient
) -> None:
    guard = SQLGuard(get_schema_context(warehouse).tables, max_rows=100)
    checked = guard.validate_and_rewrite(example.sql)
    assert checked.is_valid, checked.error

    assert warehouse.execute(checked.sql, max_rows=100)
