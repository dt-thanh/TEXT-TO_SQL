"""Integration test: the SQL guard never changes a correct answer.

Every verified gold query (eval/gold_questions.jsonl) must pass the guard, and its rewrite must
return exactly the same rows in Snowflake. This catches a rule that blocks good SQL, and a rewrite
(sqlglot printing the SQL back) that silently changes what a query means. No LLM call.
"""

from typing import Any

import pytest

from eval.run_eval import load_gold
from src.agents.text_to_sql import agent_warehouse
from src.agents.tools.schema_tools import get_schema_context
from src.services.snowflake_client import SnowflakeClient
from src.services.sql_guard import SQLGuard
from tests.integration.test_agent_permissions import agent_configured

pytestmark = pytest.mark.skipif(
    not agent_configured(), reason="Agent Snowflake user is not configured in .env"
)

GOLD = [g for g in load_gold() if g["expected_sql"]]


def canonical(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, str], ...]]:
    """Rows in a fixed order, so a query without ORDER BY still compares equal."""

    return sorted(tuple(sorted((key, repr(value)) for key, value in row.items())) for row in rows)


@pytest.fixture(scope="module")
def warehouse() -> SnowflakeClient:
    return agent_warehouse()


@pytest.fixture(scope="module")
def guard(warehouse: SnowflakeClient) -> SQLGuard:
    return SQLGuard(get_schema_context(warehouse).tables, max_rows=100)


@pytest.mark.parametrize("gold", GOLD, ids=[g["question_id"] for g in GOLD])
def test_gold_sql_passes_the_guard_and_keeps_its_answer(
    gold: dict[str, Any], guard: SQLGuard, warehouse: SnowflakeClient
) -> None:
    checked = guard.validate_and_rewrite(gold["expected_sql"])
    assert checked.is_valid, checked.error

    original = warehouse.execute(gold["expected_sql"], max_rows=100)
    rewritten = warehouse.execute(checked.sql, max_rows=100)

    assert canonical(rewritten) == canonical(original)
