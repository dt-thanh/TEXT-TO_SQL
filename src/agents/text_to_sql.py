"""The simplest Text-to-SQL loop (spec Phase 4): question → schema → LLM → SQL → Snowflake.

No LangGraph, no repair loop and no SQL guard yet (lessons 10-12). Safety today comes from the
database: the SQL runs as FINSIGHT_AGENT, a role that can only SELECT from MART, with a
statement timeout and a row cap.
"""

import json
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
from src.services.llm import LLMClient, LLMUsage
from src.services.snowflake_client import SnowflakeClient

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
    # Set when the generated SQL failed in Snowflake. The SQL is still returned: the analyst must
    # see what was tried (spec §3.1), and the repair loop (lesson 12) will feed this back.
    error: str | None = None


@lru_cache
def system_prompt() -> str:
    """Rules (prompts/system_prompt.md) plus verified examples (prompts/few_shot_examples.json)."""

    rules = (PROMPTS_DIR / "system_prompt.md").read_text(encoding="utf-8")
    examples = json.loads((PROMPTS_DIR / "few_shot_examples.json").read_text(encoding="utf-8"))
    shown = "\n\n".join(
        f"Question: {ex['question']}\nSQL:\n{ex['sql']}\nExplanation:\n{ex['explanation']}"
        for ex in examples["examples"]
    )
    return f"{rules}\n\n# Examples\n\n{shown}"


def build_user_prompt(question: str, schema_context: str, today: date) -> str:
    """Per-question message: today's date (for "last month"), the schema, then the question."""

    return (
        f"Today (UTC): {today.isoformat()}\n\n"
        f"# Schema\n{schema_context}\n\n"
        f"# Question\n{question}"
    )


def generate_sql(
    question: str, schema_context: str, llm: LLMClient, today: date | None = None
) -> GeneratedSQL:
    """Ask the model for SQL + explanation. Nothing is executed here."""

    result = llm.generate_json(
        system_prompt=system_prompt(),
        user_prompt=build_user_prompt(question, schema_context, today or datetime.now(UTC).date()),
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
    """Full loop for one question. The generated SQL is always returned, even with no rows."""

    llm = llm or LLMClient()
    warehouse = warehouse or agent_warehouse()

    generated = generate_sql(question, get_schema_context(warehouse), llm)
    if not generated.sql:
        # The model said the data cannot answer this; its explanation says why.
        return Answer(question, "", generated.explanation, [], False, generated.usage,
                      generated.llm_seconds, 0.0)  # fmt: skip

    started = time.perf_counter()
    try:
        # Read one row more than we show, only to know whether the result was cut.
        rows = warehouse.execute(generated.sql, max_rows=max_rows + 1)
    except WarehouseError as err:
        logger.warning("Generated SQL failed: %s", err)
        return Answer(
            question=question,
            sql=generated.sql,
            explanation=generated.explanation,
            rows=[],
            truncated=False,
            usage=generated.usage,
            llm_seconds=generated.llm_seconds,
            sql_seconds=time.perf_counter() - started,
            error=str(err),
        )
    sql_seconds = time.perf_counter() - started
    logger.info("SQL returned %d row(s) in %.1fs", min(len(rows), max_rows), sql_seconds)

    return Answer(
        question=question,
        sql=generated.sql,
        explanation=generated.explanation,
        rows=rows[:max_rows],
        truncated=len(rows) > max_rows,
        usage=generated.usage,
        llm_seconds=generated.llm_seconds,
        sql_seconds=sql_seconds,
    )
