"""Decide whether a generated query answered the question: compare RESULTS, not SQL text.

Two different queries can both be right (spec §28), so we run both and compare what they return.
The comparison is deliberately forgiving about presentation and strict about values:
- column names and column order do not matter (MAX_CLOSE vs max_close_price);
- extra columns in the prediction are fine (the model may add the symbol next to a number);
- row order does not matter;
- numbers match within a relative tolerance of 1e-4 (Decimal vs float arithmetic);
- a fraction shown as a percent (0.0031 vs 0.31) counts as the same number;
- a label that contains the other (BTCUSDT vs BTC) counts as the same name;
- but the number of rows must match, and every expected column must be found with the same
  values on the same rows.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

REL_TOL = 1e-4
# 1 = same unit; 100 = the prediction shows the fraction as a percent.
SCALES = (1.0, 100.0)


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    reason: str


def normalize(value: Any) -> Any:
    """One comparable form per value: numbers → float, dates → ISO text, text → trimmed upper."""

    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int | float | Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    return str(value).strip().upper()


def values_equal(expected: Any, actual: Any, scale: float = 1.0) -> bool:
    if isinstance(expected, float) and isinstance(actual, float):
        return math.isclose(expected * scale, actual, rel_tol=REL_TOL, abs_tol=1e-12)
    both_text = isinstance(expected, str) and isinstance(actual, str)
    if both_text and min(len(expected), len(actual)) >= 3:
        # Short names for the same thing: 'BTCUSDT' vs 'BTC'. Swapped labels still fail,
        # because each value must line up with the right row (see results_match step 2).
        return expected in actual or actual in expected
    return expected == actual


def sort_key(value: Any) -> tuple[int, Any]:
    """Sort mixed values (None, numbers, text) without comparing incompatible types."""

    if value is None:
        return (0, 0)
    if isinstance(value, float):
        return (1, value)
    return (2, str(value))


def column_values(rows: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {name: [normalize(row[name]) for row in rows] for name in rows[0]}


def find_scale(expected: list[Any], actual: list[Any]) -> float | None:
    """The scale at which two columns hold the same values (ignoring row order), or None."""

    for scale in SCALES:
        if scale != 1.0 and not all(isinstance(v, float) for v in expected + actual):
            continue
        expected_sorted = sorted(expected, key=sort_key)
        actual_sorted = sorted(actual, key=lambda v, s=scale: sort_key(v / s if s != 1.0 else v))
        pairs = zip(expected_sorted, actual_sorted, strict=True)
        if all(values_equal(e, a, scale) for e, a in pairs):
            return scale
    return None


def results_match(
    expected_rows: list[dict[str, Any]], actual_rows: list[dict[str, Any]]
) -> MatchResult:
    """Does the generated query's result contain the expected answer?"""

    if len(expected_rows) != len(actual_rows):
        return MatchResult(False, f"expected {len(expected_rows)} row(s), got {len(actual_rows)}")
    if not expected_rows:
        return MatchResult(True, "both results are empty")

    expected_cols = column_values(expected_rows)
    actual_cols = column_values(actual_rows)

    # 1. Give every expected column a partner column in the prediction.
    mapping: dict[str, tuple[str, float]] = {}
    for expected_name, expected_values in expected_cols.items():
        for actual_name, actual_values in actual_cols.items():
            if actual_name in {name for name, _ in mapping.values()}:
                continue
            scale = find_scale(expected_values, actual_values)
            if scale is not None:
                mapping[expected_name] = (actual_name, scale)
                break
        else:
            return MatchResult(False, f"no column holds the expected values of {expected_name}")

    # 2. Same values per column is not enough: they must also sit together on the same rows.
    names = list(mapping)
    expected_tuples = sorted(
        (tuple(expected_cols[n][i] for n in names) for i in range(len(expected_rows))),
        key=lambda t: [sort_key(v) for v in t],
    )
    actual_tuples = sorted(
        (
            tuple(
                actual_cols[mapping[n][0]][i] / mapping[n][1]
                if mapping[n][1] != 1.0
                else actual_cols[mapping[n][0]][i]
                for n in names
            )
            for i in range(len(actual_rows))
        ),
        key=lambda t: [sort_key(v) for v in t],
    )
    for expected, actual in zip(expected_tuples, actual_tuples, strict=True):
        if not all(values_equal(e, a) for e, a in zip(expected, actual, strict=True)):
            return MatchResult(False, f"row mismatch: expected {expected}, got {actual}")

    scaled = [n for n in names if mapping[n][1] != 1.0]
    note = f" (shown as percent: {', '.join(scaled)})" if scaled else ""
    return MatchResult(True, "results match" + note)
