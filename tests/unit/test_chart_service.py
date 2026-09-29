"""Unit tests for picking a chart from a query result's column types."""

from datetime import date
from decimal import Decimal

from src.services.chart_service import ChartSpec, suggest_chart


def test_a_single_row_is_shown_as_numbers_not_a_chart() -> None:
    assert suggest_chart([{"ANNUALIZED_VOLATILITY": 0.81}]) is None


def test_dates_and_numbers_make_a_line_over_time() -> None:
    rows = [
        {"TRADE_DATE": date(2026, 9, 1), "MA_7D": Decimal("64000.5"), "MA_30D": 63000.0},
        {"TRADE_DATE": date(2026, 9, 2), "MA_7D": Decimal("64100.1"), "MA_30D": 63050.0},
    ]

    assert suggest_chart(rows) == ChartSpec("line", x="TRADE_DATE", y=("MA_7D", "MA_30D"))


def test_a_label_column_draws_one_line_per_label() -> None:
    rows = [
        {"TRADE_DATE": date(2026, 9, 1), "SYMBOL": "BTCUSDT", "CLOSE_PRICE": 64000.0},
        {"TRADE_DATE": date(2026, 9, 1), "SYMBOL": "ETHUSDT", "CLOSE_PRICE": 2400.0},
    ]

    assert suggest_chart(rows) == ChartSpec("line", "TRADE_DATE", ("CLOSE_PRICE",), color="SYMBOL")


def test_labels_and_numbers_without_dates_make_bars() -> None:
    rows = [
        {"SYMBOL": "BTCUSDT", "AVG_DAILY_RETURN": 0.0031, "DAYS": 91},
        {"SYMBOL": "ETHUSDT", "AVG_DAILY_RETURN": 0.0044, "DAYS": 91},
    ]

    assert suggest_chart(rows) == ChartSpec("bar", x="SYMBOL", y=("AVG_DAILY_RETURN",))


def test_nulls_do_not_hide_a_number_column() -> None:
    # volatility_30d is NULL for an asset's first 30 days.
    rows = [
        {"TRADE_DATE": date(2019, 1, 1), "VOLATILITY_30D": None},
        {"TRADE_DATE": date(2019, 1, 31), "VOLATILITY_30D": 0.62},
    ]

    assert suggest_chart(rows) == ChartSpec("line", "TRADE_DATE", ("VOLATILITY_30D",))


def test_without_any_number_there_is_nothing_to_draw() -> None:
    rows = [{"SYMBOL": "BTCUSDT"}, {"SYMBOL": "ETHUSDT"}]

    assert suggest_chart(rows) is None


def test_true_false_columns_are_not_numbers() -> None:
    # bool is a subclass of int in Python; a chart of True/False would be meaningless.
    rows = [
        {"TRADE_DATE": date(2026, 9, 1), "IS_COMPLETE_DAY": True},
        {"TRADE_DATE": date(2026, 9, 2), "IS_COMPLETE_DAY": False},
    ]

    assert suggest_chart(rows) is None
