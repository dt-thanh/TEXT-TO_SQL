"""Validate generated SQL before it reaches Snowflake.

TODO: Delegate to SQLGuard for read-only, no-SELECT-star, and LIMIT rules.
"""

from src.agents.state import AgentState


def validate_sql(state: AgentState) -> dict[str, object]:
    """Mark placeholder SQL valid without performing real validation.

    TODO: Return structured validation errors from sqlglot parsing and policy checks.
    """

    sql = state.get("sql", "")
    return {
        "validated_sql": sql,
        "validation_passed": bool(sql),
        "error": None if sql else "No SQL was generated.",
    }
