"""Ask the model to fix its SQL, showing every failed attempt and its error."""

from typing import Any

from src.agents.sql_generation import build_repair_prompt, write_sql
from src.agents.state import AgentState
from src.services.llm import LLMClient


def repair_sql(state: AgentState, *, llm: LLMClient) -> dict[str, Any]:
    written = write_sql(build_repair_prompt(state["prompt"], state["attempts"]), llm)
    return {
        "sql": written.sql,
        "explanation": written.explanation,
        "error": None,  # a new SQL starts with a clean slate
        "violations": (),
        "repairs": state.get("repairs", 0) + 1,
        "usage": written.usage,
        "llm_seconds": written.llm_seconds,
    }
