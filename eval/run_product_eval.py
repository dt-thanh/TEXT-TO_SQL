"""Product evaluation A/B/C (spec v1.1, 7.5): what Data Engineering adds, and what AI adds on top.

Same tasks, three ways: A manual research (exchange/FRED/DefiLlama websites or APIs and a
spreadsheet), B the brief without the LLM (tables, values, signals from verified SQL), C the full
brief (writer + grounding). Each task has three equivalent variants; a person does each variant
with a different method, rotating, so no answer is remembered from an earlier method.

    python -m eval.run_product_eval worksheet --person owner   # assignment + reference answers
    (do the tasks, time them, fill the CSV)
    python -m eval.run_product_eval report eval/results/product_sheet_owner.csv

Nothing here measures people: the times and checklist results are typed into the CSV by the
person who did the task. No result is invented: without a filled sheet there is no report.
"""

import argparse
import csv
import json
import statistics
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from eval.run_eval import RESULTS_DIR, percentile, wilson_interval

TASKS = Path(__file__).with_name("product_tasks.jsonl")
METHODS = ("A", "B", "C")
SHEET_COLUMNS = [
    "person", "task_id", "variant", "method", "prompt", "seconds", "completed",
    "checklist_done", "checklist_total", "numbers_given", "numbers_correct",
    "claims_with_source", "claims_total", "llm_cost_usd", "failed_or_partial", "notes",
]  # fmt: skip


def load_tasks() -> list[dict]:
    return [json.loads(line) for line in TASKS.read_text(encoding="utf-8").splitlines() if line]


def worksheet(person: str, offset: int) -> Path:
    """One row per task: the variant and method this person uses (Latin-square rotation), and
    reference answers from the no-LLM brief for grading numbers afterwards."""

    from src.agents.research.brief import brief_to_dict, generate_brief  # needs Snowflake

    rows, answers = [], {}
    for index, task in enumerate(load_tasks()):
        for variant_index, method in enumerate(METHODS):
            variant = task["variants"][(variant_index + index + offset) % 3]
            prompt = task["prompt"].format(
                symbols=", ".join(variant["symbols"]), end=variant["end"],
                window_days=variant["window_days"],
            )  # fmt: skip
            rows.append({"person": person, "task_id": task["task_id"],
                         "variant": task["variants"].index(variant), "method": method,
                         "prompt": prompt, "checklist_total": len(task["checklist"])})  # fmt: skip
            key = f"{task['task_id']}/{task['variants'].index(variant)}"
            if key not in answers:
                brief = generate_brief(variant["symbols"], variant["window_days"], None, "en",
                                       False, as_of=date.fromisoformat(variant["end"]))  # fmt: skip
                answers[key] = {"checklist": task["checklist"], "reference": brief_to_dict(brief)}
    RESULTS_DIR.mkdir(exist_ok=True)
    sheet = RESULTS_DIR / f"product_sheet_{person}.csv"
    with sheet.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    reference = RESULTS_DIR / f"product_reference_{person}.json"
    reference.write_text(json.dumps(answers, indent=2, default=str), encoding="utf-8")
    print(f"Sheet: {sheet}\nReference answers (for grading, not for the person): {reference}")
    return sheet


def number(row: dict, column: str) -> float:
    value = (row.get(column) or "").strip()
    return float(value) if value else 0.0


def report(sheet: Path) -> dict:
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    done = [r for r in rows if (r.get("seconds") or "").strip()]
    if not done:
        raise SystemExit("No timed task in the sheet: nothing to report (no invented results).")
    result: dict = {
        "sheet": str(sheet),
        "people": sorted({r["person"] for r in done}),
        "methods": {},
    }
    for method in METHODS:
        part = [r for r in done if r["method"] == method]
        if not part:
            continue
        times = [number(r, "seconds") for r in part]
        completed = sum(r["completed"].strip().lower() in ("1", "yes", "true") for r in part)
        given = sum(number(r, "numbers_given") for r in part)
        correct = sum(number(r, "numbers_correct") for r in part)
        claims = sum(number(r, "claims_total") for r in part)
        failed = sum(r["failed_or_partial"].strip().lower() in ("1", "yes", "true") for r in part)
        result["methods"][method] = {
            "tasks": len(part),
            "completion_rate": completed / len(part),
            "completion_ci95": wilson_interval(completed, len(part)),
            "median_seconds": statistics.median(times),
            "p90_seconds": percentile(times, 0.9),
            "min_max_seconds": [min(times), max(times)],
            "numerical_correctness": correct / given if given else None,
            "checklist_coverage": sum(number(r, "checklist_done") for r in part)
            / max(1.0, sum(number(r, "checklist_total") for r in part)),
            "evidence_coverage": sum(number(r, "claims_with_source") for r in part) / claims
            if claims else None,
            "llm_cost_per_task": sum(number(r, "llm_cost_usd") for r in part) / len(part),
            "failure_rate": failed / len(part),
        }  # fmt: skip
    m = result["methods"]
    if {"A", "B", "C"} <= set(m):
        a, b, c = (m[x]["median_seconds"] for x in "ABC")
        result["time_saved"] = {
            "pulse_vs_manual": 1 - c / a,
            "data_engineering_vs_manual": 1 - b / a,
            "ai_on_top_of_data_engineering": 1 - c / b,
        }
        if (m["C"]["numerical_correctness"] or 0) < (m["B"]["numerical_correctness"] or 0):
            result["warning"] = "C has fewer correct numbers than B: the AI is damaging numbers."
    if len(result["people"]) == 1:
        result["limitation"] = (
            "One person, who built the system: times are lower than a new user's for every "
            "method, and this is not a user study."
        )
    out = RESULTS_DIR / f"product_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Report: {out}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    sheet = commands.add_parser("worksheet")
    sheet.add_argument("--person", default="owner")
    sheet.add_argument("--offset", type=int, default=0, help="Rotation for a second person")
    rep = commands.add_parser("report")
    rep.add_argument("sheet", type=Path)
    args = parser.parse_args(argv)
    if args.command == "worksheet":
        worksheet(args.person, args.offset)
    else:
        report(args.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
