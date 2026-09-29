"""Unit tests for how the benchmark grades refusals and sums up results."""

import pytest

from eval.run_eval import (
    QuestionResult,
    grade_unanswerable,
    pass_rates,
    percentile,
    wilson_interval,
)
from src.agents.text_to_sql import Answer
from src.services.llm import LLMUsage


def answer(sql: str = "", violations: tuple[str, ...] = ()) -> Answer:
    return Answer(question="q", sql=sql, explanation="", rows=[], truncated=False,
                  usage=LLMUsage(0, 0, 0.0), llm_seconds=0.0, sql_seconds=0.0,
                  violations=violations)  # fmt: skip


def result(qid: str, status: str, split: str = "dev", tags: tuple[str, ...] = ()) -> QuestionResult:
    return QuestionResult(question_id=qid, difficulty=1, question="q", status=status, reason="",
                          generated_sql="", split=split, tags=list(tags))  # fmt: skip


def test_a_question_that_must_not_be_answered_passes_when_the_model_declines() -> None:
    assert grade_unanswerable(answer(sql=""))[0] == "pass"


def test_it_also_passes_when_the_guard_stopped_the_sql_before_it_ran() -> None:
    status, reason = grade_unanswerable(answer(sql="DELETE FROM X", violations=("not_select",)))

    assert status == "pass" and "blocked" in reason


def test_it_fails_when_some_sql_actually_ran() -> None:
    status, _ = grade_unanswerable(answer(sql="SELECT close_price FROM X WHERE symbol = 'DOGE'"))

    assert status == "unexpected_sql"


def test_pass_rates_per_split_and_per_tag() -> None:
    results = [
        result("q1", "pass", "dev", ("en", "window")),
        result("q2", "wrong_result", "holdout", ("vi", "window")),
        result("q3", "pass", "holdout", ("vi",)),
    ]

    assert pass_rates(results, lambda r: [r.split]) == {"dev": (1, 1), "holdout": (1, 2)}
    by_tag = pass_rates(results, lambda r: r.tags)
    assert by_tag["window"] == (1, 2) and by_tag["vi"] == (1, 2) and by_tag["en"] == (1, 1)


def test_a_perfect_score_on_few_questions_is_still_uncertain() -> None:
    low, high = wilson_interval(10, 10)

    assert high == 1.0
    assert low == pytest.approx(0.722, abs=0.001)  # 10/10 only proves "at least ~72%"


def test_the_interval_narrows_with_more_questions() -> None:
    small = wilson_interval(9, 11)
    large = wilson_interval(90, 110)

    assert small == pytest.approx((0.523, 0.949), abs=0.001)
    assert large[1] - large[0] < small[1] - small[0]


def test_percentile_takes_the_value_at_or_above_that_share_of_questions() -> None:
    latencies = [1.0, 2.0, 3.0, 4.0, 10.0]

    assert percentile(latencies, 0.5) == 3.0
    assert percentile(latencies, 0.95) == 10.0  # the slow tail, not the average
