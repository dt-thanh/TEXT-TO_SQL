"""Build the prompts and ask the LLM for SQL: the first attempt and every repair.

The graph nodes (src/agents/nodes/) only decide WHEN to call these functions; this module decides
WHAT the model reads. Both the first attempt and a repair use the same system prompt and the same
JSON answer shape; a repair adds the failed attempts and their errors to the user message.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.agents.state import Attempt
from src.agents.tools.schema_tools import get_schema_context
from src.semantic.layer import load_semantic_layer
from src.semantic.retriever import format_context, retrieve
from src.services.llm import LLMClient, LLMUsage

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
# Long errors cost tokens and the first lines carry the cause ("invalid identifier 'X'").
MAX_ERROR_CHARS = 500

# The exact JSON shape the model must return (OpenAI Structured Outputs, strict mode).
SQL_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["sql", "explanation"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class GeneratedSQL:
    sql: str
    explanation: str
    usage: LLMUsage
    llm_seconds: float


@dataclass(frozen=True)
class Prompt:
    """Everything prepared for one question before the LLM is called."""

    user: str  # the user message: date, schema, semantic context, question
    tables: frozenset[str]  # the guard's allowlist, from the same metadata as the schema text
    retrieved: tuple[str, ...]
    data_as_of: date | None = None


@lru_cache
def system_prompt() -> str:
    """The rules (prompts/system_prompt.md). The same for every question; knowledge that depends
    on the question goes in the user message."""

    return (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")


def build_user_prompt(
    question: str,
    schema_context: str,
    today: date,
    semantic_context: str = "",
    data_as_of: date | None = None,
) -> str:
    """Per-question message: today's date (for "last month") and the newest day with data, the
    schema, what the words of the question mean in this data, then the question last."""

    semantic = f"{semantic_context}\n\n" if semantic_context else ""
    latest = f"\nLatest day with data (UTC): {data_as_of.isoformat()}" if data_as_of else ""
    return (
        f"Today (UTC): {today.isoformat()}{latest}\n\n"
        f"# Schema\n{schema_context}\n\n"
        f"{semantic}"
        f"# Question\n{question}"
    )


def prepare_prompt(question: str, warehouse: Any, today: date | None = None) -> Prompt:
    """Read the schema from Snowflake and the semantic layer from disk; no LLM call."""

    schema = get_schema_context(warehouse)
    knowledge = retrieve(question, load_semantic_layer())
    logger.info("Semantic context: %s", ", ".join(knowledge.ids) or "(no concept matched)")
    user = build_user_prompt(
        question,
        schema.prompt_text,
        today or datetime.now(UTC).date(),
        format_context(knowledge),
        schema.data_as_of,
    )
    return Prompt(user, schema.tables, knowledge.ids, schema.data_as_of)


def build_repair_prompt(user_prompt: str, attempts: list[Attempt]) -> str:
    """The original question message, then every failed attempt with its error, oldest first.

    All attempts, not only the last: the model must not go back to a query that already failed.
    """

    tried = "\n\n".join(
        f"## Attempt {number}\nSQL:\n{attempt['sql']}\nError:\n{attempt['error'][:MAX_ERROR_CHARS]}"
        for number, attempt in enumerate(attempts, start=1)
    )
    return (
        f"{user_prompt}\n\n"
        f"# Previous attempts that failed\n{tried}\n\n"
        "# Task\n"
        "Write a corrected query for the same question. Fix the cause of the last error and keep "
        "what was right. Error line numbers refer to the SQL shown with that error. If the data "
        'cannot answer the question, return "sql": "".'
    )


def write_sql(user_prompt: str, llm: LLMClient) -> GeneratedSQL:
    """Ask the model for SQL + explanation. Nothing is executed here."""

    result = llm.generate_json(
        system_prompt=system_prompt(),
        user_prompt=user_prompt,
        schema_name="sql_answer",
        json_schema=SQL_ANSWER_SCHEMA,
    )
    sql = result.data["sql"].strip().rstrip(";").strip()
    return GeneratedSQL(sql, result.data["explanation"].strip(), result.usage, result.seconds)
