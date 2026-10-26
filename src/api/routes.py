"""HTTP endpoints: /health, /ask (Text-to-SQL agent) and /research (research mode).

/ask and /research may call the LLM, so each first reserves its budget under the daily cost cap
(src/control/usage.py) and is rate limited; past the cap they answer 429 without calling it.

The route only translates: HTTP request → answer_question() → JSON response. The agent does the
work; the route never builds SQL or talks to Snowflake itself.
"""

import math
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from src.agents.chat import ChatReply, Turn, by_rule, chat, summarize_research, to_turn
from src.agents.research.report import to_markdown
from src.agents.research.workflow import ResearchAnswer, answer_research
from src.agents.text_to_sql import Answer, answer_question
from src.api.pulse import get_cost_cap
from src.api.security import note, rate_limit
from src.control.usage import BudgetExceeded, CostCap
from src.models.schemas import (
    AskRequest,
    AskResponse,
    Chart,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    ResearchChatResponse,
    ResearchResponse,
)
from src.services.chart_service import suggest_chart
from src.services.llm import LLMUsage

router = APIRouter()
public = APIRouter()  # no key needed: /health only

# Most one request may spend, reserved under the daily cap before it runs.
ASK_MAX_COST_USD = 0.01  # one SQL + up to two repairs, ~$0.002 in practice
RESEARCH_MAX_COST_USD = 0.01  # the research budget (graph.MAX_COST_USD)
CHAT_MAX_COST_USD = 0.011  # a rewrite (~$0.0003) and one /ask

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
        timings=answer.timings,
    )


@public.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """The process is up. Checks no dependency, so it works without Snowflake or LLM keys."""

    return HealthResponse(status="ok")


def within_budget(cap: CostCap, max_cost_usd: float, run: Callable[[], Any]) -> Any:
    """Run `run` under the daily cap and record what it really cost; 429 when the cap is spent."""

    try:
        with cap.reserve(max_cost_usd) as record:
            result = run()
            record(result.usage.cost_usd)
    except BudgetExceeded as err:
        raise HTTPException(
            status_code=429, detail=str(err), headers={"Retry-After": "3600"}
        ) from err
    usage = result.usage
    note(
        status=result.status,
        cost_usd=usage.cost_usd,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
    return result


@router.post("/ask", response_model=AskResponse, dependencies=[Depends(rate_limit("ask"))])
def ask(
    payload: AskRequest,
    answer_fn: Annotated[AnswerFn, Depends(get_answer_fn)],
    cap: Annotated[CostCap, Depends(get_cost_cap)],
) -> AskResponse:
    """A plain `def`, not `async def`: answer_question blocks for seconds (OpenAI, Snowflake).
    FastAPI runs a plain def in a worker thread; inside an async def the same call would freeze
    every other request until it returned."""

    return to_response(within_budget(cap, ASK_MAX_COST_USD, lambda: answer_fn(payload.question)))


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
        timings=answer.timings,
        report_markdown=to_markdown(answer),
    )


@router.post(
    "/research", response_model=ResearchResponse, dependencies=[Depends(rate_limit("research"))]
)
def research(
    payload: AskRequest,
    research_fn: Annotated[ResearchFn, Depends(get_research_fn)],
    cap: Annotated[CostCap, Depends(get_cost_cap)],
) -> ResearchResponse:
    """Research mode: planned catalog metrics, verified SQL, findings grounded in the evidence.
    A plain `def` for the same reason as /ask: the work blocks for seconds."""

    answer = within_budget(cap, RESEARCH_MAX_COST_USD, lambda: research_fn(payload.question))
    return to_research_response(answer)


def chat_cost(reply: ChatReply) -> Any:
    """The reply with what within_budget records: the rewrite plus the answer's cost."""

    answer_usage = reply.answer.usage if reply.answer is not None else None
    usage = reply.usage
    if answer_usage is not None:
        usage = LLMUsage(
            usage.input_tokens + answer_usage.input_tokens,
            usage.output_tokens + answer_usage.output_tokens,
            usage.cost_usd + answer_usage.cost_usd,
        )
    status = reply.answer.status if reply.answer is not None else reply.kind
    return SimpleNamespace(reply=reply, usage=usage, status=status)


def history_of(payload: ChatRequest) -> list[Turn]:
    return [Turn(t.question, t.standalone, t.summary) for t in payload.history]


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(rate_limit("ask"))])
def chat_message(
    payload: ChatRequest,
    answer_fn: Annotated[AnswerFn, Depends(get_answer_fn)],
    cap: Annotated[CostCap, Depends(get_cost_cap)],
) -> ChatResponse:
    """Quick SQL as a conversation (src/agents/chat.py). Greetings and requests for advice are
    answered by rules at no cost; a follow-up is rewritten into a standalone question first."""

    run = lambda: chat_cost(chat(payload.message, history_of(payload), answer_fn=answer_fn))  # noqa: E731
    # Greetings and advice requests cost nothing: no budget check (it is a Snowflake query).
    reply = (
        run().reply
        if by_rule(payload.message)
        else within_budget(cap, CHAT_MAX_COST_USD, run).reply
    )
    return ChatResponse(
        kind=reply.kind,
        message=reply.message,
        standalone_question=reply.standalone,
        reply=reply.reply,
        answer=to_response(reply.answer) if reply.answer else None,
        rewrite_usage=asdict(reply.usage),
        turn=to_turn(reply),
    )


@router.post(
    "/research/chat",
    response_model=ResearchChatResponse,
    dependencies=[Depends(rate_limit("research"))],
)
def research_chat(
    payload: ChatRequest,
    research_fn: Annotated[ResearchFn, Depends(get_research_fn)],
    cap: Annotated[CostCap, Depends(get_cost_cap)],
) -> ResearchChatResponse:
    """Research mode as a conversation: the same follow-up rewriting and rules as /chat, each
    standalone question answered by the research workflow (a report with evidence)."""

    run = lambda: chat_cost(chat(payload.message, history_of(payload), answer_fn=research_fn))  # noqa: E731
    budget = RESEARCH_MAX_COST_USD + 0.001
    reply = run().reply if by_rule(payload.message) else within_budget(cap, budget, run).reply
    return ResearchChatResponse(
        kind=reply.kind,
        message=reply.message,
        standalone_question=reply.standalone,
        reply=reply.reply,
        research=to_research_response(reply.answer) if reply.answer else None,
        rewrite_usage=asdict(reply.usage),
        turn=to_turn(reply, summarize_research),
    )
