"""HTTP endpoints: /health, and /ask which runs the Text-to-SQL agent.

The route only translates: HTTP request → answer_question() → JSON response. The agent does the
work; the route never builds SQL or talks to Snowflake itself.
"""

import math
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from src.agents.text_to_sql import Answer, answer_question
from src.models.schemas import AskRequest, AskResponse, Chart, HealthResponse
from src.services.chart_service import suggest_chart

router = APIRouter()

AnswerFn = Callable[[str], Answer]


def get_answer_fn() -> AnswerFn:
    """The agent, as a FastAPI dependency: tests swap it with app.dependency_overrides."""

    return answer_question


def to_json_value(value: Any) -> Any:
    """JSON has no Decimal, date or NaN. Snowflake returns NUMBER as Decimal and DATE as date."""

    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None  # NaN/inf are not valid JSON
    if isinstance(value, date):  # also datetime
        return value.isoformat()
    return value


def status_of(answer: Answer) -> str:
    if answer.violations:
        return "blocked"
    if answer.error:
        return "failed"
    if not answer.sql:
        return "declined"
    return "answered"


def to_response(answer: Answer) -> AskResponse:
    chart = suggest_chart(answer.rows)  # on Snowflake's own types, before JSON conversion
    return AskResponse(
        question=answer.question,
        status=status_of(answer),
        sql=answer.sql,
        explanation=answer.explanation,
        columns=list(answer.rows[0]) if answer.rows else [],
        rows=[{k: to_json_value(v) for k, v in row.items()} for row in answer.rows],
        truncated=answer.truncated,
        chart=Chart(**asdict(chart)) if chart else None,
        error=answer.error,
        violations=list(answer.violations),
        repairs=answer.repairs,
        failed_attempts=list(answer.attempts),
        retrieved=list(answer.retrieved),
        usage=asdict(answer.usage),
        llm_seconds=answer.llm_seconds,
        sql_seconds=answer.sql_seconds,
        total_seconds=answer.seconds,
        data_as_of=answer.data_as_of,
    )


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """The process is up. Checks no dependency, so it works without Snowflake or LLM keys."""

    return HealthResponse(status="ok")


@router.post("/ask", response_model=AskResponse)
def ask(payload: AskRequest, answer_fn: Annotated[AnswerFn, Depends(get_answer_fn)]) -> AskResponse:
    """A plain `def`, not `async def`: answer_question blocks for seconds (OpenAI, Snowflake).
    FastAPI runs a plain def in a worker thread; inside an async def the same call would freeze
    every other request until it returned."""

    return to_response(answer_fn(payload.question))
