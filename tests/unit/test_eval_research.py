"""Unit tests for grading research answers (src/evaluation/research.py)."""

from datetime import date
from typing import Any

from src.agents.research.workflow import ResearchAnswer
from src.evaluation.research import grade, resolve_dates
from src.services.llm import LLMUsage

GOLD = {
    "question_id": "r01", "split": "dev", "tags": ["en"], "must_decline": False,
    "expected": [{"metric_id": "period_return", "params": {"symbol": "BTCUSDT"}}],
}  # fmt: skip
GOLD_ROWS = [{"PERIOD_RETURN": 1.2003, "N_DAYS": 366.0}]


def evidence(value: float, metric_id: str = "period_return", usable: bool = True) -> dict[str, Any]:
    return {
        "id": "ev1", "metric_id": metric_id, "usable": usable,
        "values": [{"column": "PERIOD_RETURN", "value": value}, {"column": "N_DAYS", "value": 366}],
    }  # fmt: skip


def answer(status: str = "complete", items: list[Any] | None = None, **kw: Any) -> ResearchAnswer:
    items = [evidence(1.2003)] if items is None else items
    defaults = {
        "question": "q", "status": status, "evidence": items, "caveats": [],
        "findings": [{"claim": "BTC returned 120.03%.", "evidence_ids": ["ev1"]}],
        "plan": [{"metric_id": item["metric_id"]} for item in items],
        "usage": LLMUsage(1000, 100, 0.001),
    }  # fmt: skip
    return ResearchAnswer(**{**defaults, **kw})


def test_the_right_metric_with_the_right_values_and_grounded_findings_passes() -> None:
    result = grade(GOLD, answer(), GOLD_ROWS)

    assert result.passed and (result.values_matched, result.values_expected) == (1, 1)


def test_right_metric_wrong_parameters_is_wrong_values() -> None:
    assert grade(GOLD, answer(items=[evidence(0.45)]), GOLD_ROWS).status == "wrong_values"


def test_another_metric_is_wrong_metrics() -> None:
    items = [evidence(1.2003, metric_id="max_drawdown")]

    assert grade(GOLD, answer(items=items), GOLD_ROWS).status == "wrong_metrics"


def test_evidence_without_enough_data_does_not_count() -> None:
    assert grade(GOLD, answer(items=[evidence(1.2003, usable=False)]), GOLD_ROWS).status == (
        "wrong_values"
    )


def test_a_dropped_finding_is_ungrounded() -> None:
    dropped = [{"claim": "BTC returned 300%.", "rejected_numbers": ["300%"]}]

    assert grade(GOLD, answer(dropped_findings=dropped), GOLD_ROWS).status == "ungrounded"


def test_a_must_decline_question_passes_only_when_declined_without_evidence() -> None:
    gold = {**GOLD, "must_decline": True, "expected": []}

    declined = answer(status="declined", items=[], findings=[], decline_reason="No stocks.")
    answered = answer()

    assert grade(gold, declined, []).passed
    assert grade(gold, answered, []).status == "should_decline"


def test_relative_dates_resolve_against_the_newest_data_day() -> None:
    params = {"start_date": "LATEST-89", "end_date": "LATEST", "symbol": "BTCUSDT"}

    assert resolve_dates(params, date(2026, 10, 21)) == {
        "start_date": "2026-07-24", "end_date": "2026-10-21", "symbol": "BTCUSDT"
    }  # fmt: skip
