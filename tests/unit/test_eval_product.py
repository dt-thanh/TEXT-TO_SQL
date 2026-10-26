"""Product evaluation scaffolding: the tasks are well formed and the report refuses empty sheets."""

import csv
from pathlib import Path

import pytest

from eval.run_product_eval import METHODS, SHEET_COLUMNS, load_tasks, report


def test_six_to_eight_tasks_each_with_three_equivalent_variants() -> None:
    tasks = load_tasks()

    assert 6 <= len(tasks) <= 8
    for task in tasks:
        assert len(task["variants"]) == len(METHODS) == 3
        assert {len(v["symbols"]) for v in task["variants"]} == {
            len(task["variants"][0]["symbols"])
        }
        assert task["checklist"]


def test_no_report_without_measured_tasks(tmp_path: Path) -> None:
    sheet = tmp_path / "sheet.csv"
    with sheet.open("w", newline="") as handle:
        csv.DictWriter(handle, fieldnames=SHEET_COLUMNS).writeheader()

    with pytest.raises(SystemExit, match="no invented results"):
        report(sheet)


def test_the_report_computes_the_three_savings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("eval.run_product_eval.RESULTS_DIR", tmp_path)
    sheet = tmp_path / "sheet.csv"
    rows = [
        {"person": "owner", "task_id": "p01", "variant": 0, "method": m, "seconds": s,
         "completed": "yes", "checklist_done": 5, "checklist_total": 5, "numbers_given": 8,
         "numbers_correct": c, "claims_with_source": 4, "claims_total": 4, "llm_cost_usd": cost,
         "failed_or_partial": "no"}
        for m, s, c, cost in (("A", 1200, 7, 0), ("B", 300, 8, 0), ("C", 150, 8, 0.002))
    ]  # fmt: skip
    with sheet.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    result = report(sheet)

    assert result["time_saved"] == {
        "pulse_vs_manual": 0.875,
        "data_engineering_vs_manual": 0.75,
        "ai_on_top_of_data_engineering": 0.5,
    }
    assert "limitation" in result
