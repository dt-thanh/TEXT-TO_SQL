"""HTTP endpoints: /health, /ask (Text-to-SQL agent) and /research (research mode).

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

from src.agents.research.report import to_markdown
from src.agents.research.workflow import ResearchAnswer, answer_research
from src.agents.text_to_sql import Answer, answer_question
from src.models.schemas import AskRequest, AskResponse, Chart, HealthResponse, ResearchResponse
from src.services.chart_service import suggest_chart

router = APIRouter()

AnswerFn = Callable[[str], Answer]
ResearchFn = Callable[[str], ResearchAnswer]


def get_answer_fn() -> AnswerFn:
    """The agent, as a FastAPI dependency: tests swap it with app.dependency_overrides."""

    return answer_question


def get_research_fn() -> ResearchFn:
    """Research mode, as a FastAPI dependency: tests swap it with app.dependency_overrides."""

    return answer_research


def to_json_value(value: Any) -> Any:
    """JSON has no Decimal, date or NaN. Snowflake returns NUMBER as Decimal and DATE as date."""

    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None  # NaN/inf are not valid JSON
    if isinstance(value, date):  # also datetime
        return value.isoformat()
    return value


def to_response(answer: Answer) -> AskResponse:
    chart = suggest_chart(answer.rows)  # on Snowflake's own types, before JSON conversion
    return AskResponse(
        question=answer.question,
        status=answer.status,
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


def to_research_response(answer: ResearchAnswer) -> ResearchResponse:
    plan = [
        {"metric_id": step["metric_id"], "params": step["params"],
         "status": step.get("status", "skipped"), "reason": step.get("reason")}
        for step in answer.plan
    ]  # fmt: skip
    return ResearchResponse(
        question=answer.question,
        status=answer.status,
        findings=answer.findings,
        evidence=answer.evidence,
        caveats=answer.caveats,
        plan=plan,
        decline_reason=answer.decline_reason,
        analysis_window=list(answer.analysis_window) if answer.analysis_window else None,
        data_as_of=answer.data_as_of,
        usage=asdict(answer.usage),
        llm_seconds=answer.llm_seconds,
        sql_seconds=answer.sql_seconds,
        total_seconds=answer.seconds,
        report_markdown=to_markdown(answer),
    )


@router.post("/research", response_model=ResearchResponse)
def research(
    payload: AskRequest, research_fn: Annotated[ResearchFn, Depends(get_research_fn)]
) -> ResearchResponse:
    """Research mode: planned catalog metrics, verified SQL, findings grounded in the evidence.
    A plain `def` for the same reason as /ask: the work blocks for seconds."""

    return to_research_response(research_fn(payload.question))

