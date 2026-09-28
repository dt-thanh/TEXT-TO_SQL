"""The Text-to-SQL loop: question → schema + business meaning → LLM → SQL → SQL guard → Snowflake.

The model reads the MART schema (from Snowflake metadata) and the part of the semantic layer the
question needs (semantic/*.yml: coverage, metric definitions, verified examples).
No LangGraph and no repair loop yet (lesson 12). Safety comes in layers: the SQL guard only
lets one read-only query on the MART tables through and caps its rows (src/services/sql_guard.py),
then the query runs as FINSIGHT_AGENT, a role that can only SELECT from MART, with a timeout.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.agents.tools.schema_tools import get_schema_context
from src.common.config import get_settings
from src.common.exceptions import WarehouseError
from src.semantic.layer import load_semantic_layer
from src.semantic.retriever import format_context, retrieve
from src.services.llm import LLMClient, LLMUsage
from src.services.snowflake_client import SnowflakeClient
from src.services.sql_guard import SQLGuard

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
MAX_ROWS = 100
STATEMENT_TIMEOUT_SECONDS = 30

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
class Answer:
    question: str
    sql: str
    explanation: str
    rows: list[dict[str, Any]]
    truncated: bool
    usage: LLMUsage
    llm_seconds: float
    sql_seconds: float
    # Set when the SQL guard blocked the query or Snowflake rejected it. The SQL is still returned:
    # the analyst must see what was tried (spec §3.1), and the repair loop (lesson 12) will feed
    # this back.
    error: str | None = None
    violations: tuple[str, ...] = ()  # the guard's codes, only when it blocked the query
    retrieved: tuple[str, ...] = ()  # semantic concepts and examples shown to the model


@dataclass(frozen=True)
class Prompt:
    """Everything prepared for one question before the LLM is called."""

    user: str  # the user message: date, schema, semantic context, question
    tables: frozenset[str]  # the guard's allowlist, from the same metadata as the schema text
    retrieved: tuple[str, ...]


@lru_cache
def system_prompt() -> str:
    """The rules (prompts/system_prompt.md). The same for every question; knowledge that depends
    on the question goes in the user message."""

    return (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")


def build_user_prompt(
    question: str, schema_context: str, today: date, semantic_context: str = ""
) -> str:
    """Per-question message: today's date (for "last month"), the schema, what the words of the
    question mean in this data, then the question last."""

    semantic = f"{semantic_context}\n\n" if semantic_context else ""
    return (
        f"Today (UTC): {today.isoformat()}\n\n"
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
        question, schema.prompt_text, today or datetime.now(UTC).date(), format_context(knowledge)
    )
    return Prompt(user=user, tables=schema.tables, retrieved=knowledge.ids)


def generate_sql(user_prompt: str, llm: LLMClient) -> GeneratedSQL:
    """Ask the model for SQL + explanation. Nothing is executed here."""

    result = llm.generate_json(
        system_prompt=system_prompt(),
        user_prompt=user_prompt,
        schema_name="sql_answer",
        json_schema=SQL_ANSWER_SCHEMA,
    )
    sql = result.data["sql"].strip().rstrip(";").strip()
    return GeneratedSQL(sql, result.data["explanation"].strip(), result.usage, result.seconds)


def agent_warehouse() -> SnowflakeClient:
    """Snowflake connection as the read-only agent user, with a 30 s statement timeout."""

    return SnowflakeClient(
        get_settings().for_agent(),
        query_tag="finsight_agent",
        statement_timeout_seconds=STATEMENT_TIMEOUT_SECONDS,
    )


def answer_question(
    question: str,
    llm: LLMClient | None = None,
    warehouse: SnowflakeClient | None = None,
    max_rows: int = MAX_ROWS,
) -> Answer:
    """Full loop for one question. The SQL is always returned, even when nothing ran.

    `Answer.sql` is the SQL that ran: the guard's rewrite (LIMIT added, comments removed). When
    the guard blocks the query, it is the model's SQL, and nothing ran.
    """

    llm = llm or LLMClient()
    warehouse = warehouse or agent_warehouse()

    prompt = prepare_prompt(question, warehouse)
    generated = generate_sql(prompt.user, llm)
    if not generated.sql:
        # The model said the data cannot answer this; its explanation says why.
        return Answer(question, "", generated.explanation, [], False, generated.usage,
                      generated.llm_seconds, 0.0, retrieved=prompt.retrieved)  # fmt: skip

    checked = SQLGuard(prompt.tables, max_rows=max_rows).validate_and_rewrite(generated.sql)
    if not checked.is_valid:
        logger.warning("SQL guard blocked the query: %s", checked.error)
        return Answer(
            question=question,
            sql=generated.sql,
            explanation=generated.explanation,
            rows=[],
            truncated=False,
            usage=generated.usage,
            llm_seconds=generated.llm_seconds,
            sql_seconds=0.0,
            error=f"Blocked by the SQL guard: {checked.error}",
            violations=checked.violations,
            retrieved=prompt.retrieved,
        )

    started = time.perf_counter()
    try:
        # The guard's LIMIT caps the rows in Snowflake; max_rows here is a second cap on fetching.
        rows = warehouse.execute(checked.sql, max_rows=max_rows)
    except WarehouseError as err:
        logger.warning("Generated SQL failed: %s", err)
        return Answer(
            question=question,
            sql=checked.sql,
            explanation=generated.explanation,
            rows=[],
            truncated=False,
            usage=generated.usage,
            llm_seconds=generated.llm_seconds,
            sql_seconds=time.perf_counter() - started,
            error=str(err),
            retrieved=prompt.retrieved,
        )
    sql_seconds = time.perf_counter() - started
    logger.info("SQL returned %d row(s) in %.1fs", len(rows), sql_seconds)

    return Answer(
        question=question,
        sql=checked.sql,
        explanation=generated.explanation,
        rows=rows,
        # Our LIMIT was reached, so there may be more rows (or exactly max_rows; we cannot tell).
        truncated=checked.limit_enforced and len(rows) >= max_rows,
        usage=generated.usage,
        llm_seconds=generated.llm_seconds,
        sql_seconds=sql_seconds,
        retrieved=prompt.retrieved,
    )
