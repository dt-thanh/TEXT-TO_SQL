"""Generate Snowflake SQL from a question and schema context.

TODO: Call the configured LLM with system and few-shot prompts.
"""

from src.agents.state import AgentState


def generate_sql(state: AgentState) -> dict[str, object]:
    """Return deterministic placeholder SQL so the skeleton graph can run.

    TODO: Replace this placeholder with a low-temperature structured LLM call.
    """

    return {
        "sql": "SELECT 1 AS stub_value LIMIT 1",
        "error": None,
        "retries": state.get("retries", 0),
        "max_retries": state.get("max_retries", 2),
    }
