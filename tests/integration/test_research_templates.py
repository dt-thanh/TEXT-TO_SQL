"""Integration test: every research template, with its golden parameters, returns its golden values.

The values in semantic/metrics.yml were checked by an independent calculation in Python on the raw
daily closes (2026-10-22). Each template runs exactly as research mode runs it: resolved by
catalog.py, rewritten by the SQL guard, executed as the read-only agent user. No LLM call.
"""

import pytest

from src.agents.research.catalog import resolve
from src.agents.text_to_sql import agent_warehouse
from src.agents.tools.schema_tools import get_schema_context
from src.semantic.layer import Concept, load_semantic_layer
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


@pytest.mark.parametrize("metric", LAYER.research_metrics, ids=lambda m: m.id)
def test_the_template_returns_its_golden_values(
    metric: Concept, warehouse: SnowflakeClient
) -> None:
    schema = get_schema_context(warehouse)
    task = resolve(metric.id, metric.golden_case.params, LAYER, schema.data_as_of)
    checked = SQLGuard(schema.tables, max_rows=100).validate_and_rewrite(task.sql)
    assert checked.is_valid, checked.error

    rows = warehouse.execute(checked.sql, max_rows=100)

    assert len(rows) == 1
    for column, expected in metric.golden_case.expected.items():
        actual = float(rows[0][column])
        assert metric.golden_case.matches(column, actual), f"{column}: {actual} != {expected}"
