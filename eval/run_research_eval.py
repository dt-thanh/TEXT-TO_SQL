"""Benchmark research mode (eval/research_questions.jsonl), graded by src/evaluation/research.py.

For every question: run the expected catalog tasks through the verified templates (the gold
values, computed live), ask research mode, and grade metric selection, values and grounding.
Questions that must be declined pass only when declined with no evidence.

Same split rules as eval/run_eval.py: holdout questions were written before research mode ever
answered them; never change the planner, writer or catalog to fix one.

Run from the repository root:
    python -m eval.run_research_eval --gold-only        # only compute the gold values: no LLM, $0
    python -m eval.run_research_eval                    # full run: ~2-3 LLM calls per question
    python -m eval.run_research_eval --split holdout
    python -m eval.run_research_eval --only r04 r12
Each full run writes eval/results/research_<UTC timestamp>.json.
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.run_eval import RESULTS_DIR, fraction, pass_rates, percentile
from src.agents.research.catalog import TaskError, resolve
from src.agents.research.workflow import answer_research
from src.agents.text_to_sql import agent_warehouse
from src.agents.tools.schema_tools import get_schema_context
from src.common.config import get_settings
from src.common.logging_config import setup_logging
from src.evaluation.research import ResearchGrade, grade, resolve_dates
from src.semantic.layer import load_semantic_layer
from src.services.llm import LLMClient
from src.services.sql_guard import SQLGuard

QUESTIONS_FILE = Path(__file__).resolve().parent / "research_questions.jsonl"


def load_questions(only: list[str] | None, split: str | None) -> list[dict[str, Any]]:
    lines = QUESTIONS_FILE.read_text(encoding="utf-8").splitlines()
    questions = [json.loads(line) for line in lines if line.strip()]
    if only:
        questions = [q for q in questions if q["question_id"] in only]
    if split:
        questions = [q for q in questions if q["split"] == split]
    return questions


def gold_rows(question: dict[str, Any], warehouse: Any, layer: Any) -> list[dict[str, Any]]:
    """The expected values of every expected task, from the verified templates."""

    schema = get_schema_context(warehouse)
    guard = SQLGuard(schema.tables, max_rows=100)
    rows = []
    for task in question["expected"]:
        params = resolve_dates(task["params"], schema.data_as_of)
        resolved = resolve(task["metric_id"], params, layer, schema.data_as_of)
        checked = guard.validate_and_rewrite(resolved.sql)
        result = warehouse.execute(checked.sql, max_rows=100)
        row = result[0] if result else {}
        rows.append({
            o.column: (row.get(o.column).isoformat() if hasattr(row.get(o.column), "isoformat")
                       else None if row.get(o.column) is None else float(row.get(o.column)))
            for o in resolved.metric.outputs
        })  # fmt: skip
    return rows


def check_gold_only(questions: list[dict[str, Any]], warehouse: Any, layer: Any) -> int:
    failures = 0
    for question in questions:
        if question["must_decline"]:
            print(f"{question['question_id']}  (must decline: no gold)")
            continue
        try:
            rows = gold_rows(question, warehouse, layer)
        except TaskError as err:
            failures += 1
            print(f"{question['question_id']}  FAILED  {err}")
            continue
        summary = []
        for task, row in zip(question["expected"], rows, strict=True):
            metric = next(m for m in layer.research_metrics if m.id == task["metric_id"])
            n = row.get(metric.sample_column)
            enough = n is not None and n >= metric.min_observations
            if not enough:
                failures += 1
            summary.append(f"{task['metric_id']} n={n}{'' if enough else ' <- too few'}")
        print(f"{question['question_id']}  OK  " + "; ".join(summary))
    return 1 if failures else 0


def print_report(grades: list[ResearchGrade]) -> None:
    print(f"\n{'id':<4} {'split':<7} {'grade':<17} {'answer':<17} reason")
    for g in grades:
        reason = g.reason[:70]
        print(f"{g.question_id:<4} {g.split:<7} {g.status:<17} {g.answer_status:<17} {reason}")
    passed = sum(g.passed for g in grades)
    by_split = pass_rates(grades, lambda g: [g.split])
    splits = "   ".join(f"{split} {fraction(p, n)}" for split, (p, n) in by_split.items())
    answerable = [g for g in grades if g.values_expected]
    declinable = [g for g in grades if not g.values_expected]
    selection = sum(g.metric_selection for g in answerable)
    values = sum(g.values_matched for g in answerable)
    expected = sum(g.values_expected for g in answerable)
    grounded = sum(g.grounded for g in answerable)
    refused = sum(g.passed for g in declinable)
    latencies = [g.total_seconds for g in grades] or [0.0]
    cost = sum(g.cost_usd for g in grades)

    print(f"\nRESEARCH ACCURACY   {fraction(passed, len(grades))}   ({splits})")
    print(f"METRIC SELECTION    {fraction(selection, len(answerable))} of answerable questions")
    print(f"VALUES CORRECT      {fraction(values, expected)} of expected results")
    print(f"GROUNDED            {fraction(grounded, len(answerable))} of answerable questions")
    print(f"SAFE REFUSAL        {fraction(refused, len(declinable))} of must-decline questions")
    print(f"COST                ${cost:.4f}, ${cost / max(len(grades), 1):.5f} per question")
    print(f"LATENCY             p50 {percentile(latencies, 0.5):.1f}s   "
          f"p95 {percentile(latencies, 0.95):.1f}s")  # fmt: skip


def write_report(grades: list[ResearchGrade], answers: dict[str, Any]) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "run_at": stamp,
        "kind": "research",
        "model": get_settings().llm_model,
        "questions": len(grades),
        "passed": sum(g.passed for g in grades),
        "results": [asdict(g) | {"passed": g.passed, "answer": answers[g.question_id]}
                    for g in grades],
    }  # fmt: skip
    path = RESULTS_DIR / f"research_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), "utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research-mode benchmark.")
    parser.add_argument("--only", nargs="+", help="question_ids to run, e.g. r04 r12")
    parser.add_argument("--split", choices=["dev", "holdout"])
    parser.add_argument("--gold-only", action="store_true", help="only compute gold values ($0)")
    args = parser.parse_args(argv)

    setup_logging("WARNING" if get_settings().log_level == "INFO" else get_settings().log_level)
    questions = load_questions(args.only, args.split)
    warehouse, layer = agent_warehouse(), load_semantic_layer()
    if args.gold_only:
        return check_gold_only(questions, warehouse, layer)

    llm = LLMClient()
    grades, answers = [], {}
    for question in questions:
        expected = [] if question["must_decline"] else gold_rows(question, warehouse, layer)
        answer = answer_research(question["question"], llm=llm, warehouse=warehouse, layer=layer)
        grades.append(grade(question, answer, expected))
        answers[question["question_id"]] = {
            "status": answer.status, "findings": answer.findings, "plan": answer.plan,
            "caveats": answer.caveats, "dropped": answer.dropped_findings,
        }  # fmt: skip
    print_report(grades)
    path = write_report(grades, answers)
    print(f"REPORT              {path.relative_to(QUESTIONS_FILE.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
