"""Unit tests for result comparison (execution accuracy) and the gold question file."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.evaluation.compare import results_match

ROOT = Path(__file__).resolve().parents[2]


def test_names_and_column_order_do_not_matter() -> None:
    expected = [{"MAX_CLOSE_PRICE": Decimal("261.97")}]
    actual = [{"HIGHEST": 261.97}]

    assert results_match(expected, actual).matched


def test_extra_columns_and_row_order_do_not_matter() -> None:
    expected = [{"SYMBOL": "BTCUSDT", "R": 0.0031}, {"SYMBOL": "ETHUSDT", "R": 0.0044}]
    actual = [
        {"R": 0.0044, "SYMBOL": "ETHUSDT", "DAYS": 91},
        {"R": 0.0031, "SYMBOL": "BTCUSDT", "DAYS": 91},
    ]

    assert results_match(expected, actual).matched


def test_a_fraction_shown_as_percent_still_matches() -> None:
    result = results_match([{"R": -0.10278}], [{"PCT_DROP": -10.278}])

    assert result.matched
    assert "percent" in result.reason


def test_small_arithmetic_differences_are_tolerated() -> None:
    assert results_match([{"V": Decimal("0.001105944385902428")}], [{"V": 0.0011059443859}]).matched


def test_dates_and_text_compare_by_value() -> None:
    expected = [{"TRADE_DATE": date(2024, 3, 19)}]

    assert results_match(expected, [{"DAY": "2024-03-19"}]).matched


def test_short_and_long_names_for_the_same_asset_match() -> None:
    expected = [{"SYMBOL": "BTCUSDT", "R": 0.0031}, {"SYMBOL": "ETHUSDT", "R": 0.0044}]
    actual = [{"SYMBOL": "BTC", "R": 0.0031}, {"SYMBOL": "ETH", "R": 0.0044}]

    assert results_match(expected, actual).matched


def test_swapped_labels_still_fail() -> None:
    expected = [{"SYMBOL": "BTCUSDT", "R": 0.0031}, {"SYMBOL": "ETHUSDT", "R": 0.0044}]
    swapped = [{"SYMBOL": "ETH", "R": 0.0031}, {"SYMBOL": "BTC", "R": 0.0044}]

    assert not results_match(expected, swapped).matched


def test_wrong_value_fails_and_says_which_column() -> None:
    result = results_match([{"DAYS": 208}], [{"DAYS": 207}])

    assert not result.matched
    assert "DAYS" in result.reason


def test_wrong_row_count_fails() -> None:
    result = results_match([{"SYMBOL": "BTCUSDT"}], [{"SYMBOL": "BTCUSDT"}, {"SYMBOL": "ETHUSDT"}])

    assert not result.matched
    assert "row(s)" in result.reason


def test_values_must_sit_on_the_same_rows() -> None:
    expected = [{"SYMBOL": "BTCUSDT", "R": 0.1}, {"SYMBOL": "ETHUSDT", "R": 0.2}]
    swapped = [{"SYMBOL": "BTCUSDT", "R": 0.2}, {"SYMBOL": "ETHUSDT", "R": 0.1}]

    assert not results_match(expected, swapped).matched


def test_gold_file_is_well_formed_and_does_not_leak_few_shot_examples() -> None:
    gold_lines = (ROOT / "eval" / "gold_questions.jsonl").read_text(encoding="utf-8").splitlines()
    gold = [json.loads(line) for line in gold_lines]
    examples = json.loads((ROOT / "prompts" / "few_shot_examples.json").read_text(encoding="utf-8"))
    few_shot_questions = {ex["question"].strip().lower() for ex in examples["examples"]}

    ids = [g["question_id"] for g in gold]
    assert len(ids) == len(set(ids)), "question_id must be unique"
    for g in gold:
        assert {"question_id", "difficulty", "question", "expected_sql"} <= g.keys()
        # A benchmark question the model saw as an example measures copying, not skill.
        assert g["question"].strip().lower() not in few_shot_questions
