"""Unit tests for the Streamlit screen, driven by Streamlit's AppTest with a fake API.

AppTest runs ui/streamlit_app.py in this process, so replacing httpx.post replaces the API.
"""

from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[3] / "ui" / "streamlit_app.py")
SQL = "SELECT\n  symbol,\n  AVG(daily_return) AS r\nFROM FINSIGHT.MART.MART_ASSET_DAILY\nLIMIT 100"
BASE = {
    "question": "Q", "status": "answered", "sql": SQL, "explanation": "1. Average per asset.",
    "columns": ["SYMBOL", "R"],
    "rows": [{"SYMBOL": "BTCUSDT", "R": 0.0031}, {"SYMBOL": "ETHUSDT", "R": 0.0044}],
    "truncated": False, "chart": {"kind": "bar", "x": "SYMBOL", "y": ["R"], "color": None},
    "error": None, "violations": [], "repairs": 0, "failed_attempts": [], "retrieved": [],
    "usage": {"input_tokens": 2000, "output_tokens": 150, "cost_usd": 0.0004},
    "llm_seconds": 2.0, "sql_seconds": 0.5, "total_seconds": 3.1, "data_as_of": "2026-09-28",
}  # fmt: skip


def run_app(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any] | Exception) -> AppTest:
    """Type a question, click Ask, with the API answering `reply` (or failing with it)."""

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.text_area(key="question").input("Average daily return of BTC and ETH?").run()
    app.button[0].click().run()
    assert not app.exception
    return app


def test_the_sql_is_shown_on_the_main_screen_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    app = run_app(monkeypatch, BASE)

    assert app.code[0].value == SQL
    assert all(code.value != SQL for code in app.expander[0].code)  # not only in "Details"
    assert [h.value for h in app.subheader][:4] == ["Answer", "Chart", "Result data",
                                                    "Generated SQL"]  # fmt: skip


def test_the_screen_says_up_to_which_day_the_data_goes(monkeypatch: pytest.MonkeyPatch) -> None:
    app = run_app(monkeypatch, BASE)

    assert any("Data up to 2026-09-28" in caption.value for caption in app.caption)


def test_a_single_row_answer_is_shown_as_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    one_row = BASE | {"rows": [{"ANNUALIZED_VOLATILITY": 0.8101352}], "chart": None}

    app = run_app(monkeypatch, one_row)

    assert [(m.label, m.value) for m in app.metric] == [("ANNUALIZED_VOLATILITY", "0.810135")]


def test_a_declined_question_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    declined = BASE | {"status": "declined", "sql": "", "rows": [], "chart": None,
                       "explanation": "There is no stock data."}  # fmt: skip

    app = run_app(monkeypatch, declined)

    assert app.info[0].value == "There is no stock data."
    assert "no SQL" in app.code[0].value


def test_a_failed_query_shows_the_error_and_every_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = {"sql": "SELECT x", "error": "invalid identifier 'X'"}
    failed = BASE | {"status": "failed", "rows": [], "chart": None, "repairs": 2,
                     "error": attempt["error"], "failed_attempts": [attempt] * 3}  # fmt: skip

    app = run_app(monkeypatch, failed)

    assert app.error[0].value == "invalid identifier 'X'"
    assert len(app.expander[0].code) == 3


def test_one_click_is_one_paid_call_and_the_button_comes_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(kwargs["json"]["question"])
        return httpx.Response(200, json=BASE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.text_area(key="question").input("Average daily return?").run()
    app.button[0].click().run()

    assert calls == ["Average daily return?"]
    assert not app.button[0].disabled  # locked only while the call runs, then usable again
    assert "pending" not in app.session_state


def test_an_api_that_is_down_gives_a_hint_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    app = run_app(monkeypatch, httpx.ConnectError("connection refused"))

    assert "make run" in app.error[0].value
