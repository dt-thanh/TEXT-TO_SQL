"""Answer one question: run the Text-to-SQL graph and turn its final state into an Answer.

The steps live in src/agents/graph.py: schema + business meaning → LLM → SQL guard → Snowflake,
with a bounded repair loop that sends a guard or compilation error back to the model.
Safety comes in layers: the SQL guard only lets one read-only query on the MART tables through
and caps its rows (src/services/sql_guard.py), then the query runs as FINSIGHT_AGENT, a role that
can only SELECT from MART, with a timeout.
"""

import logging
import time
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from src.agents.graph import MAX_REPAIRS, build_graph
from src.agents.state import AgentState, Attempt
from src.common.config import get_settings
from src.services.llm import LLMClient, LLMUsage
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)

MAX_ROWS = 100
STATEMENT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class Answer:
    question: str
    sql: str
    explanation: str
    rows: list[dict[str, Any]]
    truncated: bool
    usage: LLMUsage  # summed over the first attempt and every repair
    llm_seconds: float
    sql_seconds: float
    # Set when the last attempt was blocked by the SQL guard or failed in Snowflake. The SQL is
    # still returned: the analyst must see what was tried (spec §3.1).
    error: str | None = None
    violations: tuple[str, ...] = ()  # the guard's codes, only when it blocked the last SQL
    retrieved: tuple[str, ...] = ()  # semantic concepts and examples shown to the model
    repairs: int = 0
    attempts: tuple[Attempt, ...] = ()  # every failed attempt, oldest first
    seconds: float = 0.0  # wall-clock time of the whole question, metadata lookup included
    data_as_of: date | None = None  # newest finished UTC day in the marts: answers stop there

    @property
    def status(self) -> str:
        """How the question ended: answered, declined, blocked or failed."""

        if self.violations:
            return "blocked"  # the SQL guard refused the last SQL; nothing ran
        if self.error:
            return "failed"  # Snowflake rejected the last SQL after the allowed repairs
        if not self.sql:
            return "declined"  # the data cannot answer the question
        return "answered"


@lru_cache
def agent_warehouse() -> SnowflakeClient:
    """The read-only agent user's Snowflake client, one per process, with a 30 s statement
    timeout. It keeps its connection open, so questions after the first skip the ~2 s login."""

    return SnowflakeClient(
        get_settings().for_agent(),
        query_tag="finsight_agent",
        statement_timeout_seconds=STATEMENT_TIMEOUT_SECONDS,
        keep_connection=True,
    )


def to_answer(state: AgentState, max_rows: int, seconds: float = 0.0) -> Answer:
    """The graph's final state, in the shape the CLI, the eval and the API use."""

    error = state.get("error")
    violations = state.get("violations", ())
    sql = state.get("sql", "")
    rows = [] if error else state.get("rows", [])
    return Answer(
        question=state["question"],
        # What ran (the guard's rewrite), or the model's SQL when nothing ran.
        sql=sql if violations or not sql else state.get("safe_sql", sql),
        explanation=state.get("explanation", ""),
        rows=rows,
        # Our LIMIT was reached, so there may be more rows (or exactly max_rows; we cannot tell).
        truncated=bool(rows) and state.get("limit_enforced", False) and len(rows) >= max_rows,
        usage=state.get("usage", LLMUsage(0, 0, 0.0)),
        llm_seconds=state.get("llm_seconds", 0.0),
        sql_seconds=state.get("sql_seconds", 0.0),
        error=error,
        violations=violations,
        retrieved=state.get("retrieved", ()),
        repairs=state.get("repairs", 0),
        attempts=tuple(state.get("attempts", [])),
        seconds=seconds,
        data_as_of=state.get("data_as_of"),
    )


def answer_question(
    question: str,
    llm: LLMClient | None = None,
    warehouse: SnowflakeClient | None = None,
    max_rows: int = MAX_ROWS,
    max_repairs: int = MAX_REPAIRS,
) -> Answer:
    """Full workflow for one question. The SQL is always returned, even when nothing ran."""

    llm = llm or LLMClient()
    warehouse = warehouse or agent_warehouse()
    graph = build_graph(llm, warehouse, max_rows=max_rows, max_repairs=max_repairs)
    started = time.perf_counter()
    state = graph.invoke({"question": question})
    answer = to_answer(state, max_rows, seconds=time.perf_counter() - started)
    # One line per question: enough to follow cost, latency and quality from the logs.
    logger.info(
        "question status=%s repairs=%d rows=%d cost_usd=%.5f seconds=%.1f retrieved=%s text=%r",
        answer.status,
        answer.repairs,
        len(answer.rows),
        answer.usage.cost_usd,
        answer.seconds,
        ",".join(answer.retrieved) or "-",
        question[:200],
    )
    return answer
