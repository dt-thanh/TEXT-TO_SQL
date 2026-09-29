"""First attempt: ask the model for SQL."""

from typing import Any

from src.agents.sql_generation import write_sql
from src.agents.state import AgentState
from src.services.llm import LLMClient


def generate_sql(state: AgentState, *, llm: LLMClient) -> dict[str, Any]:
    written = write_sql(state["prompt"], llm)
    return {
        "sql": written.sql,
        "explanation": written.explanation,
        "error": None,  # a new SQL starts with a clean slate
        "violations": (),
        "usage": written.usage,
        "llm_seconds": written.llm_seconds,
    }
