"""Turn SQL results into a concise natural-language answer.

TODO: Ask the configured LLM to explain bounded, serialized result rows.
"""

from src.agents.state import AgentState


def explain_result(state: AgentState) -> dict[str, object]:
    """Return a placeholder explanation for the executable skeleton.

    TODO: Generate a grounded answer and explicitly handle empty result sets.
    """

    return {"explanation": "TODO: Explain the Snowflake query result with an LLM."}
