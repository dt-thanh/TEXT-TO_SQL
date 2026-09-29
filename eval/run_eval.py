"""Benchmark the Text-to-SQL agent by EXECUTION ACCURACY (spec §28).

For every gold question: run the verified SQL (the expected answer), ask the agent, run its SQL,
and compare the two results with src/evaluation/compare.py. Both queries run as the read-only
agent user. Expected answers are computed live, so questions stay valid as new data arrives.

Two splits (the `split` field of each gold question):
- dev: questions we looked at while building the agent. Tuning on them is allowed, so their score
  is optimistic.
- holdout: questions written before the agent ever saw them. Never change the prompt, the
  semantic layer or the guard to fix one holdout question: that turns it into a dev question.
  Their score is the honest estimate for new questions.

Run from the repository root:
    python -m eval.run_eval --gold-only        # only check the gold SQL runs: no LLM, $0
    python -m eval.run_eval                    # full benchmark: one LLM call per question
    python -m eval.run_eval --split holdout    # only the holdout questions
    python -m eval.run_eval --only q04 q10     # re-run a few questions while debugging
    python -m eval.run_eval --regrade eval/results/run_X.json   # grade saved SQL again: no LLM, $0
Each full run writes eval/results/run_<UTC timestamp>.json.
"""

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agents.text_to_sql import Answer, agent_warehouse, answer_question
from src.agents.tools.schema_tools import get_schema_context
from src.common.config import get_settings
from src.common.exceptions import FinSightError, LLMError
from src.common.logging_config import setup_logging
from src.evaluation.compare import results_match
from src.services.llm import LLMClient
from src.services.sql_guard import SQLGuard

EVAL_DIR = Path(__file__).resolve().parent
GOLD_FILE = EVAL_DIR / "gold_questions.jsonl"
RESULTS_DIR = EVAL_DIR / "results"
MAX_ROWS = 100

logger = logging.getLogger(__name__)


@dataclass
class QuestionResult:
    question_id: str
    difficulty: int
    question: str
    status: str  # pass | wrong_result | blocked | sql_error | no_sql | unexpected_sql | llm_error
    reason: str
    generated_sql: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_seconds: float = 0.0
    sql_seconds: float = 0.0
    split: str = "dev"
    tags: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)  # semantic concepts/examples shown
    repairs: int = 0  # LLM calls spent fixing a failed attempt
    attempt_errors: list[str] = field(default_factory=list)  # last line of each failed attempt

    @property
    def passed(self) -> bool:
        return self.status == "pass"


def load_gold(only: list[str] | None = None, split: str | None = None) -> list[dict[str, Any]]:
    lines = GOLD_FILE.read_text(encoding="utf-8").splitlines()
    gold = [json.loads(line) for line in lines if line.strip()]
    if only:
        gold = [g for g in gold if g["question_id"] in only]
    if split:
        gold = [g for g in gold if g["split"] == split]
    return gold


def grade_unanswerable(answer: Answer) -> tuple[str, str]:
    """For a question the data cannot (or must not) answer: it passes only if no SQL ran."""

    if not answer.sql:
        return "pass", "declined, as expected"
    if answer.violations:
        return "pass", "the SQL guard blocked the SQL, nothing ran"
    return "unexpected_sql", "should have declined: this data cannot answer it"


def evaluate(gold: dict[str, Any], llm: LLMClient, warehouse: Any) -> QuestionResult:
    """Ask one gold question and grade the agent's answer against the expected result."""

    base = {"question_id": gold["question_id"], "difficulty": gold["difficulty"],
            "question": gold["question"], "split": gold["split"], "tags": gold["tags"]}  # fmt: skip
    try:
        answer = answer_question(gold["question"], llm=llm, warehouse=warehouse, max_rows=MAX_ROWS)
    except LLMError as err:
        return QuestionResult(**base, status="llm_error", reason=str(err), generated_sql="")

    spent = {"input_tokens": answer.usage.input_tokens, "output_tokens": answer.usage.output_tokens,
             "cost_usd": answer.usage.cost_usd, "llm_seconds": answer.llm_seconds,
             "sql_seconds": answer.sql_seconds,
             "retrieved": list(answer.retrieved), "repairs": answer.repairs,
             "attempt_errors": [a["error"].splitlines()[-1] for a in answer.attempts]}  # fmt: skip
    result = {**base, **spent, "generated_sql": answer.sql}

    if gold["expected_sql"] is None:  # the right answer is "this data cannot (must not) answer"
        status, reason = grade_unanswerable(answer)
        return QuestionResult(**result, status=status, reason=reason)
    if not answer.sql:
        return QuestionResult(**result, status="no_sql", reason=answer.explanation[:200])
    if answer.violations:  # the SQL guard refused it: nothing ran
        return QuestionResult(**result, status="blocked", reason=answer.error[:300])
    if answer.error:
        return QuestionResult(**result, status="sql_error", reason=answer.error[:300])

    expected_rows = warehouse.execute(gold["expected_sql"], max_rows=MAX_ROWS)
    match = results_match(expected_rows, answer.rows)
    return QuestionResult(**result, status="pass" if match.matched else "wrong_result",
                          reason=match.reason)  # fmt: skip


def check_gold_only(golds: list[dict[str, Any]], warehouse: Any) -> int:
    """Run every gold SQL once. Costs nothing on the LLM side."""

    failures = 0
    for gold in golds:
        if gold["expected_sql"] is None:
            print(f"{gold['question_id']}  (unanswerable: no SQL to check)")
            continue
        try:
            rows = warehouse.execute(gold["expected_sql"], max_rows=MAX_ROWS)
            # An empty expected answer cannot tell a right query from a wrong one.
            warning = "  <- no rows: is the question well chosen?" if not rows else ""
            print(f"{gold['question_id']}  OK  {len(rows)} row(s){warning}")
        except FinSightError as err:
            failures += 1
            print(f"{gold['question_id']}  FAILED  {err}")
    return 1 if failures else 0


def regrade(report_file: Path, golds: list[dict[str, Any]], warehouse: Any) -> list[QuestionResult]:
    """Grade the SQL saved in an earlier report again, e.g. after fixing the comparison.

    No LLM call: generating and grading are separate steps, so improving the grader costs $0 and
    judges exactly the same SQL as before. The saved SQL goes through today's SQL guard, as the
    agent's SQL does, so this also measures what a new guard rule would block.
    """

    gold_by_id = {g["question_id"]: g for g in golds}
    guard = SQLGuard(get_schema_context(warehouse).tables, max_rows=MAX_ROWS)
    saved = json.loads(report_file.read_text(encoding="utf-8"))["results"]
    results = []
    for old in saved:
        # Reports written before a field existed simply lack it: keep its default.
        saved_fields = {f.name: old[f.name] for f in fields(QuestionResult) if f.name in old}
        result = QuestionResult(**saved_fields)
        gold = gold_by_id.get(result.question_id)
        if gold:  # split and tags come from today's gold file
            result.split, result.tags = gold["split"], gold["tags"]
        if gold and gold["expected_sql"] and result.status in ("pass", "wrong_result", "blocked"):
            checked = guard.validate_and_rewrite(result.generated_sql)
            if checked.is_valid:
                expected_rows = warehouse.execute(gold["expected_sql"], max_rows=MAX_ROWS)
                actual_rows = warehouse.execute(checked.sql, max_rows=MAX_ROWS)
                match = results_match(expected_rows, actual_rows)
                result.status = "pass" if match.matched else "wrong_result"
                result.reason = match.reason
            else:
                result.status, result.reason = "blocked", checked.error or ""
        results.append(result)
    return results


def write_report(results: list[QuestionResult], kind: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "run_at": stamp,
        "kind": kind,
        "model": get_settings().llm_model,
        "questions": len(results),
        "passed": sum(r.passed for r in results),
        "results": [asdict(r) | {"passed": r.passed} for r in results],
    }
    path = RESULTS_DIR / f"{kind}_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def pass_rates(
    results: list[QuestionResult], groups_of: Callable[[QuestionResult], list[Any]]
) -> dict[Any, tuple[int, int]]:
    """(passed, total) per group. A question can be in several groups, e.g. several tags."""

    counts: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        for group in groups_of(r):
            counts[group][0] += r.passed
            counts[group][1] += 1
    return {group: (p, n) for group, (p, n) in sorted(counts.items())}


def percentile(values: list[float], share: float) -> float:
    """Nearest-rank percentile: the smallest value that `share` of the values are at or below."""

    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def wilson_interval(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a pass rate measured on `total` questions (Wilson score).

    With few questions the true rate is uncertain: 10/10 is compatible with a system that gets
    only ~72% of new questions right. Two splits whose intervals overlap are not shown different.
    """

    if total == 0:
        return 0.0, 1.0
    rate = passed / total
    center = (rate + z * z / (2 * total)) / (1 + z * z / total)
    spread = math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
    half = z * spread / (1 + z * z / total)
    return max(0.0, center - half), min(1.0, center + half)


def fraction(passed: int, total: int) -> str:
    low, high = wilson_interval(passed, total)
    return f"{passed}/{total} = {passed / max(total, 1):.0%} [95% CI {low:.0%}-{high:.0%}]"


def print_report(results: list[QuestionResult]) -> None:
    print(f"\n{'id':<4} {'split':<7} {'lvl':>3}  {'status':<14} reason")
    for r in results:
        print(f"{r.question_id:<4} {r.split:<7} {r.difficulty:>3}  {r.status:<14} {r.reason[:80]}")

    passed = sum(r.passed for r in results)
    by_split = pass_rates(results, lambda r: [r.split])
    by_level = pass_rates(results, lambda r: [r.difficulty])
    by_tag = pass_rates(results, lambda r: r.tags)
    splits = "   ".join(f"{split} {fraction(p, n)}" for split, (p, n) in by_split.items())
    levels = "  ".join(f"L{level}: {p}/{n}" for level, (p, n) in by_level.items())
    tags = "  ".join(f"{tag} {p}/{n}" for tag, (p, n) in by_tag.items())
    with_sql = [r for r in results if r.generated_sql]
    ran = [r for r in with_sql if r.status in ("pass", "wrong_result", "unexpected_sql")]
    latencies = [r.llm_seconds + r.sql_seconds for r in results] or [0.0]
    cost = sum(r.cost_usd for r in results)
    tokens_in = sum(r.input_tokens for r in results)
    tokens_out = sum(r.output_tokens for r in results)

    print(f"\nEXECUTION ACCURACY  {fraction(passed, len(results))}   ({splits})")
    print(f"BY LEVEL            {levels}")
    print(f"BY TAG              {tags}")
    print(f"SQL RAN             {fraction(len(ran), len(with_sql))} of the SQL the model wrote "
          "passed the guard and ran without error")
    repaired = [r for r in results if r.repairs]
    fixed = sum(r.passed for r in repaired)
    print(f"REPAIRS             {len(repaired)} question(s) repaired, {fixed} of them now pass "
          f"({sum(r.repairs for r in results)} repair call(s))")
    print(f"COST                ${cost:.4f}  ({tokens_in} input + {tokens_out} output tokens), "
          f"${cost / max(len(results), 1):.5f} per question")
    print(f"LATENCY             p50 {percentile(latencies, 0.5):.1f}s   "
          f"p95 {percentile(latencies, 0.95):.1f}s   (LLM + Snowflake, per question)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execution-accuracy benchmark.")
    parser.add_argument("--only", nargs="+", help="question_ids to run, e.g. q04 q10")
    parser.add_argument("--split", choices=["dev", "holdout"], help="only this split")
    parser.add_argument("--gold-only", action="store_true", help="only run the gold SQL ($0)")
    parser.add_argument("--regrade", type=Path, help="grade a saved report again ($0)")
    args = parser.parse_args(argv)

    setup_logging("WARNING" if get_settings().log_level == "INFO" else get_settings().log_level)
    golds = load_gold(args.only, args.split)
    warehouse = agent_warehouse()
    if args.gold_only:
        return check_gold_only(golds, warehouse)
    if args.regrade:
        results = regrade(args.regrade, golds, warehouse)
        kind = "regrade"
    else:
        llm = LLMClient()
        results = [evaluate(gold, llm, warehouse) for gold in golds]
        kind = "run"

    print_report(results)
    path = write_report(results, kind)
    print(f"REPORT              {path.relative_to(EVAL_DIR.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
