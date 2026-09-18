"""Repair invalid or failed SQL using error feedback.

TODO: Feed SQL, schema context, and sanitized errors back to the LLM.
"""

from src.agents.state import AgentState


def repair_sql(state: AgentState) -> dict[str, object]:
    """Increment retry state while retaining placeholder SQL.

    TODO: Replace the retained SQL with the model's corrected SQL output.
    """

    return {
        "sql": state.get("sql", "SELECT 1 AS stub_value LIMIT 1"),
        "retries": state.get("retries", 0) + 1,
        "error": None,
    }
