"""Multi-row catalog metrics: symbol lists, per-row evidence, grounding, report (spec v1.1, 4.5)."""

from datetime import date
from typing import Any

import pytest

from src.agents.research.catalog import TaskError, resolve
from src.agents.research.graph import run_task
from src.agents.research.grounding import ungrounded
from src.agents.research.report import rows_table
from src.semantic.layer import load_semantic_layer, with_universe

LAYER = load_semantic_layer()
DATA_AS_OF = date(2026, 10, 25)
YEAR = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
TABLES = frozenset(
    f"FINSIGHT.MART.{t}"
    for t in ("MART_ASSET_DAILY", "MART_RISK_SIGNAL_DAILY", "MART_ASSET_UNIVERSE")
)


class RowsWarehouse:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.sql: list[str] = []

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        self.sql.append(sql)
        return self.rows


def state() -> dict[str, Any]:
    return {"data_as_of": DATA_AS_OF, "allowed_tables": TABLES}


def test_a_symbol_list_becomes_quoted_literals() -> None:
    task = resolve(
        "watchlist_snapshot", {"symbols": " btcusdt, ETHUSDT ", **YEAR}, LAYER, DATA_AS_OF
    )

    assert task.params["symbols"] == "BTCUSDT,ETHUSDT"
    assert "symbol IN ('BTCUSDT', 'ETHUSDT')" in task.sql


@pytest.mark.parametrize(
    "symbols, message",
    [
        ("", "1 to 10"),
        ("BTCUSDT,BTCUSDT", "different"),
        (",".join(["BTCUSDT"] * 11), "1 to 10"),
        ("BTCUSDT,LINKUSDT", "is not one of the ready"),  # not loaded yet: refused before SQL
        ("BTCUSDT') OR ('1'='1", "is not one of the ready"),
    ],
)
def test_symbol_lists_are_checked_like_symbols(symbols: str, message: str) -> None:
    with pytest.raises(TaskError, match=message):
        resolve("watchlist_snapshot", {"symbols": symbols, **YEAR}, LAYER, DATA_AS_OF)


def test_an_added_asset_is_accepted_once_it_is_ready_in_the_universe() -> None:
    universe = [
        {"SYMBOL": "BTCUSDT", "BASE_ASSET": "BTC", "STATUS": "ready", "IS_CORE": True},
        {"SYMBOL": "LINKUSDT", "BASE_ASSET": "LINK", "STATUS": "ready", "IS_CORE": False},
    ]

    task = resolve(
        "watchlist_snapshot",
        {"symbols": "BTCUSDT,LINKUSDT", **YEAR},
        with_universe(LAYER, universe),
        DATA_AS_OF,
    )

    assert "'LINKUSDT'" in task.sql


def test_each_row_is_judged_on_its_own_sample() -> None:
    # A coin listed last week has 5 days: its row is unusable, the others still count.
    rows = [
        {"SYMBOL": "BTCUSDT", "LAST_CLOSE": 87648.22, "PERIOD_RETURN": -0.0633,
         "ANNUALIZED_VOLATILITY": 0.4167, "MAX_DRAWDOWN": -0.32, "N_DAYS": 365,
         "DATA_THROUGH": date(2025, 12, 31)},
        {"SYMBOL": "ETHUSDT", "LAST_CLOSE": 2971.64, "PERIOD_RETURN": -0.11,
         "ANNUALIZED_VOLATILITY": 0.74, "MAX_DRAWDOWN": -0.60, "N_DAYS": 5,
         "DATA_THROUGH": date(2025, 12, 31)},
    ]  # fmt: skip
    task = {"metric_id": "watchlist_snapshot", "params": {"symbols": "BTCUSDT,ETHUSDT", **YEAR}}

    status, evidence, _ = run_task(0, task, state(), RowsWarehouse(rows), LAYER)

    assert status["status"] == "done" and evidence["usable"] and evidence["n"] == 1
    btc, eth = evidence["rows"]
    assert btc["key"] == {"SYMBOL": "BTCUSDT"} and btc["usable"]
    assert not eth["usable"]
    assert btc["values"][-1] == {
        "column": "DATA_THROUGH", "value": "2025-12-31", "unit": "date",
        "description": "Newest day with data in the period.",
    }  # fmt: skip


def test_no_risk_signal_is_an_answer_not_missing_data() -> None:
    task = {"metric_id": "risk_signals", "params": {"symbols": "BTCUSDT", **YEAR}}

    status, evidence, _ = run_task(0, task, state(), RowsWarehouse([]), LAYER)

    assert status["status"] == "done" and evidence["usable"] and evidence["rows"] == []


def test_each_signal_row_carries_its_own_unit() -> None:
    rows = [
        {"SYMBOL": "ETHUSDT", "SIGNAL_ID": "abnormal_move", "DAYS_FIRED": 8,
         "LAST_FIRED": date(2025, 10, 10), "LAST_VALUE": 3.4748, "THRESHOLD": 3, "UNIT": "sigma"},
        {"SYMBOL": "ETHUSDT", "SIGNAL_ID": "drawdown_alert", "DAYS_FIRED": 168,
         "LAST_FIRED": date(2025, 12, 31), "LAST_VALUE": -0.3656, "THRESHOLD": -0.2,
         "UNIT": "fraction"},
    ]  # fmt: skip
    task = {"metric_id": "risk_signals", "params": {"symbols": "ETHUSDT", **YEAR}}

    _, evidence, _ = run_task(0, task, state(), RowsWarehouse(rows), LAYER)

    units = [
        {v["column"]: v["unit"] for v in row["values"]}["LAST_VALUE"] for row in evidence["rows"]
    ]
    assert units == ["sigma", "fraction"]
    table = "\n".join(rows_table(evidence["rows"]))
    assert "3.47 sd" in table and "-36.56%" in table


def test_grounding_checks_numbers_against_every_row() -> None:
    evidence = {
        "id": "ev1", "params": {"symbols": "BTCUSDT,ETHUSDT"}, "values": [], "n": 2,
        "rows": [
            {"key": {"SYMBOL": "BTCUSDT"}, "n": 365, "usable": True,
             "values": [{"column": "PERIOD_RETURN", "value": -0.0633, "unit": "fraction"}]},
            {"key": {"SYMBOL": "ETHUSDT"}, "n": 365, "usable": True,
             "values": [{"column": "PERIOD_RETURN", "value": -0.1097, "unit": "fraction"}]},
        ],
    }  # fmt: skip
    question = "How did my watchlist do?"

    assert (
        ungrounded("BTC -6.33%, ETH -10.97% over 365 days.", [evidence], question, [evidence]) == []
    )
    assert ungrounded("ETH fell 25%.", [evidence], question, [evidence]) == ["25%"]
