"""The state the Text-to-SQL graph carries from node to node (spec §21).

A node receives the whole state and returns only the keys it changes; LangGraph merges them in.
Most keys are REPLACED by the newest value. Five keys ADD UP instead, through a reducer
(the function in Annotated[...]):
- attempts: every failed SQL with its error, so a repair sees all of them;
- usage, llm_seconds, sql_seconds: cost and time over every call, repairs included;
- timings: seconds per node (add_timings), to see which step made a request slow.

Per-attempt keys (sql, error, violations, retryable) describe the CURRENT attempt only: every new
SQL (generate_sql, repair_sql) resets error and violations, so nothing stale survives a repair.
"""

import operator
import time
from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, TypedDict

from src.services.llm import LLMUsage


def add_timings(total: dict[str, float] | None, new: dict[str, float]) -> dict[str, float]:
    """Reducer: seconds spent in each graph node, summed over repeated visits (a repair loop)."""

    merged = dict(total or {})
    for node, seconds in new.items():
        merged[node] = merged.get(node, 0.0) + seconds
    return merged


def timed(name: str, node: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Wrap a graph node so its update also reports how long it took (state key `timings`)."""

    def run(state: Any) -> dict[str, Any]:
        started = time.perf_counter()
        update = node(state)
        return {**update, "timings": {name: round(time.perf_counter() - started, 4)}}

    return run


class Attempt(TypedDict):
    sql: str  # the SQL the error is about (for a Snowflake error: the guard's rewrite that ran)
    error: str


def add_usage(total: LLMUsage | None, new: LLMUsage) -> LLMUsage:
    """Reducer: sum tokens and cost of every LLM call."""

    if total is None:
        return new
    return LLMUsage(
        input_tokens=total.input_tokens + new.input_tokens,
        output_tokens=total.output_tokens + new.output_tokens,
        cost_usd=total.cost_usd + new.cost_usd,
    )


class AgentState(TypedDict, total=False):
    # Input
    question: str

    # Prepared once by retrieve_context
    prompt: str  # the user message: date, schema, semantic context, question
    allowed_tables: frozenset[str]  # the SQL guard's allowlist
    retrieved: tuple[str, ...]  # semantic concepts and examples shown to the model
    data_as_of: date | None  # newest finished UTC day in the marts

    # The current attempt
    sql: str  # what the model wrote ("" = the data cannot answer the question)
    explanation: str
    safe_sql: str  # the guard's rewrite: what runs in Snowflake
    limit_enforced: bool
    rows: list[dict[str, Any]]
    error: str | None  # why the current attempt failed (guard or Snowflake)
    violations: tuple[str, ...]  # the guard's codes, when it blocked the current SQL
    retryable: bool  # could the model fix `error` by rewriting the SQL?

    # Bookkeeping over all attempts
    repairs: int
    attempts: Annotated[list[Attempt], operator.add]
    usage: Annotated[LLMUsage, add_usage]
    llm_seconds: Annotated[float, operator.add]
    sql_seconds: Annotated[float, operator.add]
    timings: Annotated[dict[str, float], add_timings]  # seconds per node
