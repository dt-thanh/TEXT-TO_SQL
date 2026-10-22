"""Ask the model for a research plan: which catalog metrics, with which parameters.

The model sees the whole catalog (ten metrics, small enough to show every time), the data that
exists and the dates. It answers in a strict JSON shape whose metric_id is an enum of the catalog,
so it cannot name a metric that does not exist; parameters are checked later by catalog.resolve.
"""

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from typing import Any

from src.agents.sql_generation import PROMPTS_DIR
from src.semantic.layer import Concept, SemanticLayer
from src.semantic.retriever import RetrievedContext, format_context
from src.services.llm import LLMClient, LLMUsage

# The plan may use at most this many metrics: each one is a query and evidence to explain.
MAX_TASKS = 4


@dataclass(frozen=True)
class PlannedTask:
    metric_id: str
    params: dict[str, str]


@dataclass(frozen=True)
class Plan:
    tasks: tuple[PlannedTask, ...]
    decline_reason: str
    usage: LLMUsage
    seconds: float


@lru_cache
def planner_prompt() -> str:
    return (PROMPTS_DIR / "research_planner.md").read_text(encoding="utf-8")


def plan_schema(metric_ids: list[str]) -> dict[str, Any]:
    param = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
        "required": ["name", "value"],
        "additionalProperties": False,
    }
    task = {
        "type": "object",
        "properties": {
            "metric_id": {"type": "string", "enum": metric_ids},
            "params": {"type": "array", "items": param},
        },
        "required": ["metric_id", "params"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "tasks": {"type": "array", "items": task},
            "decline_reason": {"type": "string"},
        },
        "required": ["tasks", "decline_reason"],
        "additionalProperties": False,
    }


def describe_metric(metric: Concept) -> str:
    lines = [f"## {metric.id}: {metric.name}", f"Meaning: {' '.join(metric.definition.split())}"]
    lines.append("Parameters:")
    for param in metric.params:
        bounds = ""
        if param.minimum is not None or param.maximum is not None:
            bounds = f", from {param.minimum} to {param.maximum}"
        lines.append(f"- {param.name} ({param.type}{bounds}): {param.description}")
    results = ", ".join(output.column.lower() for output in metric.outputs)
    lines.append(f"Results: {results}")
    if metric.pitfalls:
        lines.append(f"Pitfall: {' '.join(metric.pitfalls.split())}")
    return "\n".join(lines)


def build_planner_message(
    question: str, layer: SemanticLayer, today: date, data_as_of: date | None
) -> str:
    latest = f"\nLatest day with data (UTC): {data_as_of.isoformat()}" if data_as_of else ""
    coverage = format_context(RetrievedContext(layer.coverage, (), ()))
    catalog = "\n\n".join(describe_metric(metric) for metric in layer.research_metrics)
    return (
        f"Today (UTC): {today.isoformat()}{latest}\n\n"
        f"{coverage}\n\n"
        f"# Metric catalog\n{catalog}\n\n"
        f"# Question\n{question}"
    )


def make_plan(
    question: str, layer: SemanticLayer, llm: LLMClient, today: date, data_as_of: date | None
) -> Plan:
    ids = [metric.id for metric in layer.research_metrics]
    result = llm.generate_json(
        system_prompt=planner_prompt(),
        user_prompt=build_planner_message(question, layer, today, data_as_of),
        schema_name="research_plan",
        json_schema=plan_schema(ids),
        max_output_tokens=700,
    )
    tasks = tuple(
        PlannedTask(task["metric_id"], {p["name"]: p["value"] for p in task["params"]})
        for task in result.data["tasks"][:MAX_TASKS]
    )
    return Plan(tasks, result.data["decline_reason"].strip(), result.usage, result.seconds)
