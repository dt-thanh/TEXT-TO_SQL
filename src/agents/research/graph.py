"""The research workflow as a LangGraph state machine (spec v1.1, section 5).

    START → prepare → plan ─(declined / no task)───────────────────────────→ END
                        │
                        ▼
                     execute ─(no usable evidence)─────────────────────────→ END
                        │
                        ▼
              ┌──→ write → check ─(grounded, or out of attempts/budget)────→ END
              └────────────────┘ (a number not in the evidence: write again, once)

prepare reads the schema metadata (newest data day, table allowlist). plan asks the model for
catalog metrics and parameters. execute resolves each task (catalog.py), runs its template
through the SQL guard as the read-only agent role, and turns the row into evidence. write asks
the model for findings; check verifies every number against the evidence (grounding.py).
"""

import logging
import operator
import time
from datetime import date
from functools import partial
from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.research.catalog import TaskError, resolve
from src.agents.research.grounding import ungrounded
from src.agents.research.planning import make_plan
from src.agents.research.writing import automatic_caveats, language_of, write_findings
from src.agents.state import add_usage
from src.agents.tools.schema_tools import get_schema_context
from src.common.exceptions import WarehouseError
from src.semantic.layer import SemanticLayer
from src.services.llm import LLMUsage
from src.services.sql_guard import SQLGuard

logger = logging.getLogger(__name__)

# Budgets of one research question (spec v1.1, 5.5).
MAX_WRITES = 2  # the first findings, and one rewrite when a number is not in the evidence
MAX_SECONDS = 60.0  # remaining tasks are skipped past this
MAX_COST_USD = 0.01  # no rewrite once spent
MAX_ROWS = 100  # templates return one row; the guard's cap still applies
RECURSION_LIMIT = 25


class ResearchState(TypedDict, total=False):
    question: str
    today: date
    started: float  # time.perf_counter() at the start

    data_as_of: date | None
    allowed_tables: frozenset[str]

    tasks: list[dict[str, Any]]  # planned: {metric_id, params}
    decline_reason: str
    plan_status: list[dict[str, Any]]  # per task: metric_id, params, status, reason
    evidence: list[dict[str, Any]]

    findings: list[dict[str, Any]]
    writer_caveats: list[str]
    rejected_numbers: list[str]  # numbers of the last findings not found in the evidence
    dropped: list[dict[str, Any]]  # findings removed after the last attempt
    writes: int

    usage: Annotated[LLMUsage, add_usage]
    llm_seconds: Annotated[float, operator.add]
    sql_seconds: Annotated[float, operator.add]


def prepare(state: ResearchState, *, warehouse: Any) -> dict[str, Any]:
    schema = get_schema_context(warehouse)
    return {"data_as_of": schema.data_as_of, "allowed_tables": schema.tables}


def plan(state: ResearchState, *, llm: Any, layer: SemanticLayer) -> dict[str, Any]:
    made = make_plan(state["question"], layer, llm, state["today"], state.get("data_as_of"))
    tasks = [{"metric_id": t.metric_id, "params": t.params} for t in made.tasks]
    return {
        "tasks": tasks,
        "decline_reason": made.decline_reason,
        "usage": made.usage,
        "llm_seconds": made.seconds,
    }


def result_value(value: Any, unit: str) -> float | str | None:
    """A result as JSON can hold it: dates as ISO text, everything else as a float."""

    if value is None or isinstance(value, bool):
        return None
    if unit == "date":
        return value.isoformat() if isinstance(value, date) else str(value)
    return float(value)


def run_task(
    index: int, task: dict[str, Any], state: ResearchState, warehouse: Any, layer: SemanticLayer
) -> tuple[dict[str, Any], dict[str, Any] | None, float]:
    """(plan status, evidence or None, seconds spent in Snowflake) for one planned task."""

    status = {"metric_id": task["metric_id"], "params": task["params"], "reason": None}
    try:
        resolved = resolve(task["metric_id"], task["params"], layer, state.get("data_as_of"))
    except TaskError as err:
        return {**status, "status": "failed", "reason": str(err)}, None, 0.0

    guard = SQLGuard(state["allowed_tables"], max_rows=MAX_ROWS)
    checked = guard.validate_and_rewrite(resolved.sql)
    if not checked.is_valid:  # a template the guard refuses is a bug in the catalog
        return {**status, "status": "failed", "reason": f"SQL guard: {checked.error}"}, None, 0.0

    started = time.perf_counter()
    try:
        rows = warehouse.execute(checked.sql, max_rows=MAX_ROWS)
    except WarehouseError as err:
        seconds = time.perf_counter() - started
        return {**status, "status": "failed", "reason": str(err)[:300]}, None, seconds
    seconds = time.perf_counter() - started

    metric = resolved.metric
    row = rows[0] if rows else {}
    values = [
        {"column": o.column, "value": result_value(row.get(o.column), o.unit), "unit": o.unit,
         "description": o.description}
        for o in metric.outputs
    ]  # fmt: skip
    n = row.get(metric.sample_column)
    n = int(n) if n is not None else None
    main_value = values[0]["value"]
    usable = n is not None and n >= metric.min_observations and main_value is not None
    params = resolved.params
    evidence = {
        "id": f"ev{index + 1}",
        "metric_id": metric.id,
        "metric_name": metric.name,
        "definition": metric.definition,
        "params": params,
        "sql": checked.sql,
        "sources": list(metric.sources),
        "data_window": f"{params.get('start_date', '')}..{params.get('end_date', '')}",
        "n": n,
        "values": values,
        "pit_mode": metric.pit_mode,
        "usable": usable,
    }
    status = {**status, "params": params, "status": "done"}
    if not usable:
        reason = f"not enough data: n={n}, needs {metric.min_observations}"
        status = {**status, "status": "insufficient_data", "reason": reason}
    return status, evidence, seconds


def execute(state: ResearchState, *, warehouse: Any, layer: SemanticLayer) -> dict[str, Any]:
    plan_status, evidence, sql_seconds = [], [], 0.0
    for index, task in enumerate(state["tasks"]):
        if time.perf_counter() - state["started"] > MAX_SECONDS:
            plan_status.append({**task, "status": "skipped", "reason": "time budget spent"})
            continue
        status, item, seconds = run_task(index, task, state, warehouse, layer)
        plan_status.append(status)
        sql_seconds += seconds
        if item:
            evidence.append(item)
    return {"plan_status": plan_status, "evidence": evidence, "sql_seconds": sql_seconds}


def usable_evidence(state: ResearchState) -> list[dict[str, Any]]:
    return [item for item in state.get("evidence", []) if item["usable"]]


def write(state: ResearchState, *, llm: Any) -> dict[str, Any]:
    evidence = usable_evidence(state)
    language = language_of(state["question"])
    shown = automatic_caveats(evidence, state.get("data_as_of"), language)
    written = write_findings(
        state["question"], evidence, shown, llm, state.get("rejected_numbers") or None
    )
    return {
        "findings": written.findings,
        "writer_caveats": written.caveats,
        "writes": state.get("writes", 0) + 1,
        "usage": written.usage,
        "llm_seconds": written.seconds,
    }


def check(state: ResearchState) -> dict[str, Any]:
    """Grounding: keep the findings whose every number is in the evidence they cite."""

    evidence = usable_evidence(state)
    by_id = {item["id"]: item for item in evidence}
    kept, dropped, rejected = [], [], []
    for finding in state.get("findings", []):
        cited = [by_id[i] for i in finding["evidence_ids"] if i in by_id]
        bad = (
            ungrounded(finding["claim"], cited, state["question"], evidence)
            if cited
            else ["(cites no evidence)"]
        )
        if bad:
            dropped.append({**finding, "rejected_numbers": bad})
            rejected += bad
        else:
            kept.append(finding)
    return {"findings": kept, "dropped": dropped, "rejected_numbers": rejected}


def route_after_plan(state: ResearchState) -> Literal["execute", "end"]:
    return "execute" if state.get("tasks") else "end"


def route_after_execute(state: ResearchState) -> Literal["write", "end"]:
    return "write" if usable_evidence(state) else "end"


def route_after_check(state: ResearchState) -> Literal["write", "end"]:
    spent = state["usage"].cost_usd if state.get("usage") else 0.0
    if state.get("dropped") and state.get("writes", 0) < MAX_WRITES and spent < MAX_COST_USD:
        return "write"
    return "end"


def build_research_graph(llm: Any, warehouse: Any, layer: SemanticLayer) -> Any:
    builder = StateGraph(ResearchState)
    builder.add_node("prepare", partial(prepare, warehouse=warehouse))
    builder.add_node("plan", partial(plan, llm=llm, layer=layer))
    builder.add_node("execute", partial(execute, warehouse=warehouse, layer=layer))
    builder.add_node("write", partial(write, llm=llm))
    builder.add_node("check", check)

    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "plan")
    builder.add_conditional_edges("plan", route_after_plan, {"execute": "execute", "end": END})
    builder.add_conditional_edges("execute", route_after_execute, {"write": "write", "end": END})
    builder.add_edge("write", "check")
    builder.add_conditional_edges("check", route_after_check, {"write": "write", "end": END})
    return builder.compile()
