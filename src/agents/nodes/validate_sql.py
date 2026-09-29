"""Run the SQL guard (src/services/sql_guard.py) on the model's SQL. Nothing reaches Snowflake."""

from typing import Any

from src.agents.state import AgentState, Attempt
from src.services.sql_guard import SQLGuard

# Violations that show an attempt to write or to break out of the rules. They are final: asking
# the model to "fix" a DELETE would only teach it to get around the guard.
FINAL_VIOLATIONS = frozenset(
    {"not_select", "forbidden_statement", "multiple_statements", "forbidden_function"}
)


def validate_sql(state: AgentState, *, max_rows: int) -> dict[str, Any]:
    guard = SQLGuard(state["allowed_tables"], max_rows=max_rows)
    checked = guard.validate_and_rewrite(state["sql"])
    if checked.is_valid:
        return {"safe_sql": checked.sql, "limit_enforced": checked.limit_enforced, "error": None}

    # A mistake like SELECT * or a short table name is worth one more try.
    error = f"Blocked by the SQL guard: {checked.error}"
    return {
        "error": error,
        "violations": checked.violations,
        "retryable": not FINAL_VIOLATIONS.intersection(checked.violations),
        "attempts": [Attempt(sql=state["sql"], error=error)],
    }
