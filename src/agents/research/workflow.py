"""Answer one research question: run the research graph and turn its final state into an answer.

Status, decided by code from what happened (never by the model):
- declined: the planner found no catalog metric for the question (e.g. it asks about stocks);
- error: nothing could run (every task failed: bad parameters, Snowflake errors);
- insufficient_data: tasks ran, but no result had enough observations;
- partial: some task failed or was skipped, or a finding was dropped by the grounding check;
- complete: every task ran with enough data and every finding is grounded.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from src.agents.research.graph import RECURSION_LIMIT, build_research_graph, usable_evidence
from src.agents.research.writing import automatic_caveats, language_of, new_caveats
from src.agents.text_to_sql import agent_warehouse
from src.semantic.layer import SemanticLayer, load_semantic_layer
from src.services.llm import LLMClient, LLMUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResearchAnswer:
    question: str
    status: str
    findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    caveats: list[str]
    plan: list[dict[str, Any]]
    decline_reason: str = ""
    dropped_findings: list[dict[str, Any]] = field(default_factory=list)
    usage: LLMUsage = field(default_factory=lambda: LLMUsage(0, 0, 0.0))
    llm_seconds: float = 0.0
    sql_seconds: float = 0.0
    seconds: float = 0.0
    data_as_of: date | None = None
    timings: dict[str, float] = field(default_factory=dict)  # seconds per graph node

    @property
    def analysis_window(self) -> tuple[str, str] | None:
        """Earliest start and latest end over the evidence, or None."""

        starts = [e["params"]["start_date"] for e in self.evidence if "start_date" in e["params"]]
        ends = [e["params"]["end_date"] for e in self.evidence if "end_date" in e["params"]]
        return (min(starts), max(ends)) if starts and ends else None


def decide_status(state: dict[str, Any]) -> str:
    if not state.get("tasks"):
        return "declined" if state.get("decline_reason") else "error"
    statuses = [task["status"] for task in state.get("plan_status", [])]
    if not usable_evidence(state):
        return "insufficient_data" if "insufficient_data" in statuses else "error"
    if any(s != "done" for s in statuses) or state.get("dropped") or state.get("writer_error"):
        return "partial"
    return "complete"


def to_research_answer(state: dict[str, Any], seconds: float) -> ResearchAnswer:
    evidence = usable_evidence(state)
    caveats = automatic_caveats(evidence, state.get("data_as_of"), language_of(state["question"]))
    caveats += new_caveats(state.get("writer_caveats", []), caveats)
    return ResearchAnswer(
        question=state["question"],
        status=decide_status(state),
        findings=state.get("findings", []),
        evidence=state.get("evidence", []),
        caveats=caveats,
        plan=state.get("plan_status", state.get("tasks", [])),
        decline_reason=state.get("decline_reason", ""),
        dropped_findings=state.get("dropped", []),
        usage=state.get("usage", LLMUsage(0, 0, 0.0)),
        llm_seconds=state.get("llm_seconds", 0.0),
        sql_seconds=state.get("sql_seconds", 0.0),
        seconds=seconds,
        data_as_of=state.get("data_as_of"),
        timings=dict(state.get("timings", {})),
    )


def answer_research(
    question: str,
    llm: LLMClient | None = None,
    warehouse: Any = None,
    layer: SemanticLayer | None = None,
    today: date | None = None,
) -> ResearchAnswer:
    """Full research workflow for one question. Numbers come only from catalog SQL."""

    llm = llm or LLMClient()
    warehouse = warehouse or agent_warehouse()
    graph = build_research_graph(llm, warehouse, layer or load_semantic_layer())
    started = time.perf_counter()
    state = graph.invoke(
        {"question": question, "today": today or datetime.now(UTC).date(), "started": started},
        config={"recursion_limit": RECURSION_LIMIT},
    )
    answer = to_research_answer(state, time.perf_counter() - started)
    logger.info(
        "research status=%s tasks=%d evidence=%d findings=%d dropped=%d cost_usd=%.5f "
        "seconds=%.1f timings=%s text=%r",
        answer.status,
        len(answer.plan),
        len(usable_evidence(state)),
        len(answer.findings),
        len(answer.dropped_findings),
        answer.usage.cost_usd,
        answer.seconds,
        answer.timings,
        question[:200],
    )
    return answer
