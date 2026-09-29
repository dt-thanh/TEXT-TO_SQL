"""Prepare what the model reads: MART schema (Snowflake metadata) and semantic knowledge."""

from typing import Any

from src.agents.sql_generation import prepare_prompt
from src.agents.state import AgentState


def retrieve_context(state: AgentState, *, warehouse: Any) -> dict[str, Any]:
    """Runs once per question, before any LLM call. The repair loop reuses the result."""

    prompt = prepare_prompt(state["question"], warehouse)
    return {"prompt": prompt.user, "allowed_tables": prompt.tables, "retrieved": prompt.retrieved}
