"""Benchmark the Daily Brief on eval/brief_cases.jsonl (answers written before any run).

    python -m eval.run_brief_eval            # with the writer: ~$0.002 per case
    python -m eval.run_brief_eval --no-llm   # tables, values and signals only: $0
Writes eval/results/brief_<timestamp>.json and prints one line per case.
"""

import argparse
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from eval.run_eval import RESULTS_DIR, percentile, wilson_interval
from src.agents.research.brief import generate_brief
from src.agents.text_to_sql import agent_warehouse
from src.common.config import get_settings
from src.common.logging_config import setup_logging
from src.evaluation.brief import grade_brief

CASES = Path(__file__).with_name("brief_cases.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args(argv)
    setup_logging(get_settings().log_level)

    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    cases = [c for c in cases if not args.only or c["case_id"] in args.only]
    warehouse = agent_warehouse()
    grades = []
    for case in cases:
        brief = generate_brief(
            case["symbols"], case["window_days"], None, case["language"], not args.no_llm,
            warehouse=warehouse, as_of=date.fromisoformat(case["as_of"]),
        )  # fmt: skip
        result = grade_brief(case, brief, used_llm=not args.no_llm)
        grades.append(result)
        failed = [name for name, ok in result.checks.items() if not ok]
        verdict = "PASS" if result.passed else "FAIL"
        print(
            f"{case['case_id']} {case['split']:7} {verdict} status={result.status} "
            f"{result.seconds:.1f}s ${result.cost_usd:.5f} findings={result.findings} "
            f"dropped={result.dropped} failed={failed or '-'}"
        )
        for problem in result.problems:
            print("    ", problem)

    report = {"run_at": datetime.now(UTC).isoformat(), "used_llm": not args.no_llm,
              "model": get_settings().llm_model, "cases": [asdict(g) for g in grades]}  # fmt: skip
    for split in ("dev", "holdout"):
        part = [g for g in grades if g.split == split]
        if part:
            passed = sum(g.passed for g in part)
            low, high = wilson_interval(passed, len(part))
            report[split] = {"passed": passed, "total": len(part), "ci95": [low, high]}
            print(f"{split}: {passed}/{len(part)} [{low:.0%}-{high:.0%}]")
    seconds = [g.seconds for g in grades]
    if seconds:
        report["p50_seconds"], report["p95_seconds"] = (
            percentile(seconds, 0.5),
            percentile(seconds, 0.95),
        )
        report["cost_usd"] = sum(g.cost_usd for g in grades)
        print(f"p50 {report['p50_seconds']:.1f}s p95 {report['p95_seconds']:.1f}s, "
              f"total ${report['cost_usd']:.4f}")  # fmt: skip
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"brief_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"Report: {path}")
    return 0 if all(g.passed for g in grades) else 1


if __name__ == "__main__":
    sys.exit(main())
