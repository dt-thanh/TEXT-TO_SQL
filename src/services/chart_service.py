"""Pick a chart for a query result from its column types alone (spec §26 "CHART").

Fixed rules instead of asking the LLM: free, instant, the same every time, and they can never
name a column that is not in the result.
- fewer than 2 rows: no chart; one row is a few numbers, shown as numbers;
- a date column and numbers: a line over time, one line per label (e.g. SYMBOL) if there is one;
- a text column and numbers: bars, one per label;
- anything else: no chart, the table says it all.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class ChartSpec:
    kind: Literal["line", "bar"]
    x: str
    y: tuple[str, ...]
    color: str | None = None  # one line per value of this column


def is_number(value: Any) -> bool:
    # bool is a subclass of int in Python; True/False is not a measure to draw.
    return isinstance(value, int | float | Decimal) and not isinstance(value, bool)


def is_day(value: Any) -> bool:
    return isinstance(value, date)  # a datetime is a date too


def is_label(value: Any) -> bool:
    return isinstance(value, str)


def columns_where(rows: list[dict[str, Any]], test: Callable[[Any], bool]) -> list[str]:
    """Columns that have at least one value and whose non-NULL values all pass `test`."""

    found = []
    for column in rows[0]:
        values = [row[column] for row in rows if row[column] is not None]
        if values and all(test(v) for v in values):
            found.append(column)
    return found


def suggest_chart(rows: list[dict[str, Any]]) -> ChartSpec | None:
    """`rows` as returned by Snowflake: Python dates and numbers, before any JSON conversion."""

    if len(rows) < 2:
        return None
    numbers = columns_where(rows, is_number)
    if not numbers:
        return None
    days = columns_where(rows, is_day)
    labels = columns_where(rows, is_label)
    if days and labels:  # long format: one measure, one line per label
        return ChartSpec("line", x=days[0], y=(numbers[0],), color=labels[0])
    if days:
        return ChartSpec("line", x=days[0], y=tuple(numbers))
    if labels:
        return ChartSpec("bar", x=labels[0], y=(numbers[0],))
    return None
