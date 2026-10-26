"""Grade one Daily Brief against a case of eval/brief_cases.jsonl (spec v1.1, 7.3 BRIEF, T5.5).

Checks, each pass/fail: the plan is the code-built one (no planner call), every asset's return
and drawdown match the independent answer, the risk signals are exactly the expected ones, every
finding passed the number check at the first write, and the budgets held (90 s, $0.02).
"""

from dataclasses import dataclass, field
from typing import Any

from src.agents.research.brief import MAX_COST_USD, MAX_SECONDS, BriefAnswer

TOLERANCE = 1e-6  # relative; the same closes, different arithmetic order


@dataclass
class BriefGrade:
    case_id: str
    split: str
    status: str
    checks: dict[str, bool]
    seconds: float
    cost_usd: float
    findings: int
    dropped: int
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


def close(expected: float, actual: float | None) -> bool:
    return actual is not None and abs(actual - expected) <= TOLERANCE * max(1.0, abs(expected))


def grade_brief(case: dict[str, Any], brief: BriefAnswer, used_llm: bool) -> BriefGrade:
    answer, problems = brief.research, []
    plan_ids = [step["metric_id"] for step in answer.plan]
    plan_ok = plan_ids[:2] == ["data_status", "watchlist_snapshot"] and "risk_signals" in plan_ids
    period_ok = brief.start is not None and brief.start.isoformat() == case["expected_start"]

    snapshot = {}
    for item in answer.evidence:
        if item["metric_id"] == "watchlist_snapshot":
            for row in item["rows"]:
                snapshot[row["key"]["SYMBOL"]] = {v["column"]: v["value"] for v in row["values"]}
    values_ok = True
    for symbol, expected in case["expected_assets"].items():
        actual = snapshot.get(symbol, {})
        for column, value in expected.items():
            if not close(value, actual.get(column)):
                values_ok = False
                problems.append(f"{symbol} {column}: {actual.get(column)} != {value}")

    signals = sorted([s["assets"], s["signal_id"]] for s in brief.signals)
    signals_ok = signals == case["expected_signals"]
    if not signals_ok:
        problems.append(f"signals {signals} != {case['expected_signals']}")

    checks = {
        "plan": plan_ok,
        "period": period_ok,
        "values": values_ok,
        "signals": signals_ok,
        "within_budget": answer.seconds <= MAX_SECONDS and answer.usage.cost_usd <= MAX_COST_USD,
    }
    if used_llm:
        checks["grounded"] = bool(answer.findings) and not answer.dropped_findings
    return BriefGrade(
        case["case_id"], case["split"], brief.status, checks, answer.seconds,
        answer.usage.cost_usd, len(answer.findings), len(answer.dropped_findings), problems,
    )  # fmt: skip
