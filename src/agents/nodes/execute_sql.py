"""Execute validated SQL through the Snowflake client.

TODO: Inject SnowflakeClient and map connector failures into agent state.
"""

from src.agents.state import AgentState


def execute_sql(state: AgentState) -> dict[str, object]:
    """Return an empty placeholder result without contacting Snowflake.

    TODO: Execute only validated_sql with timeouts, row caps, and query tagging.
    """

    if not state.get("validated_sql"):
        return {
            "execution_succeeded": False,
            "error": "No validated SQL is available.",
        }
    return {"result": [], "execution_succeeded": True, "error": None}
