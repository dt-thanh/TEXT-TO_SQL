"""Grade research answers against expected catalog tasks (eval/research_questions.jsonl).

A research question lists the tasks a correct plan contains: catalog metrics with parameters.
Their expected values are computed live, by running the same verified templates, so the grade
does not go stale as data arrives. A research answer passes when:
- metric selection: every expected metric appears in the plan;
- values: for every expected task, some usable evidence of that metric has the same values
  (which only happens when the planner chose the right parameters);
- grounding: there is at least one finding, and none was dropped by the grounding check.
A question that must be declined passes when the answer is declined and no evidence exists.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

REL_TOL = 1e-6
# "LATEST" or "LATEST-89": a day relative to the newest day with data, for relative questions.
RELATIVE_DAY = re.compile(r"^LATEST(?:-(\d+))?$")


@dataclass
class ResearchGrade:
    question_id: str
    split: str
    # pass | declined_wrongly | should_decline | wrong_metrics | wrong_values | ungrounded | error
    status: str
    reason: str
    answer_status: str
    metric_selection: bool
    values_matched: int
    values_expected: int
    grounded: bool
    tags: list[str] = field(default_factory=list)
    planned_metrics: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    total_seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def resolve_dates(params: dict[str, str], data_as_of: date) -> dict[str, str]:
    """Replace LATEST / LATEST-n with real dates."""

    resolved = {}
    for name, value in params.items():
        match = RELATIVE_DAY.match(value)
        if match:
            value = (data_as_of - timedelta(days=int(match.group(1) or 0))).isoformat()
        resolved[name] = value
    return resolved


def same_value(expected: Any, actual: Any) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if isinstance(expected, str) or isinstance(actual, str):
        return str(expected) == str(actual)
    return abs(float(actual) - float(expected)) <= REL_TOL * max(1.0, abs(float(expected)))


def evidence_matches(item: dict[str, Any], metric_id: str, gold_row: dict[str, Any]) -> bool:
    if item["metric_id"] != metric_id or not item["usable"]:
        return False
    values = {v["column"]: v["value"] for v in item["values"]}
    return all(same_value(gold, values.get(column)) for column, gold in gold_row.items())


def grade(
    gold: dict[str, Any],
    answer: Any,
    gold_rows: list[dict[str, Any]],
) -> ResearchGrade:
    """`answer` is a ResearchAnswer; `gold_rows[i]` holds the values of gold["expected"][i]."""

    planned = [step["metric_id"] for step in answer.plan]
    base = {
        "question_id": gold["question_id"], "split": gold["split"], "tags": gold["tags"],
        "answer_status": answer.status, "planned_metrics": planned,
        "cost_usd": answer.usage.cost_usd, "total_seconds": answer.seconds,
    }  # fmt: skip
    if gold["must_decline"]:
        declined = answer.status == "declined" and not answer.evidence
        status = "pass" if declined else "should_decline"
        reason = (answer.decline_reason or "declined") if declined else f"answered: {planned}"
        return ResearchGrade(**base, status=status, reason=reason[:200], metric_selection=declined,
                             values_matched=0, values_expected=0, grounded=declined)  # fmt: skip

    expected = [task["metric_id"] for task in gold["expected"]]
    selection = set(expected) <= set(planned)
    matched = sum(
        any(evidence_matches(item, task["metric_id"], row) for item in answer.evidence)
        for task, row in zip(gold["expected"], gold_rows, strict=True)
    )
    grounded = bool(answer.findings) and not answer.dropped_findings
    counts = {"metric_selection": selection, "values_matched": matched,
              "values_expected": len(expected), "grounded": grounded}  # fmt: skip

    if answer.status == "declined":
        status, reason = "declined_wrongly", answer.decline_reason
    elif answer.status == "error":
        status, reason = "error", "; ".join(str(s.get("reason")) for s in answer.plan)
    elif not selection:
        status, reason = "wrong_metrics", f"expected {expected}, planned {planned}"
    elif matched < len(expected):
        status, reason = "wrong_values", f"{matched}/{len(expected)} expected results matched"
    elif not grounded:
        status, reason = "ungrounded", f"{len(answer.dropped_findings)} finding(s) dropped"
    else:
        status, reason = "pass", f"{matched}/{len(expected)} results matched, grounded"
    return ResearchGrade(**base, status=status, reason=str(reason)[:200], **counts)
