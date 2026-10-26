"""The Ask (chat) tab and the language switch, driven by Streamlit's AppTest with a fake API.

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
    "timings": {},
}  # fmt: skip


def chat_reply(answer: dict | None, standalone: str | None = None, kind: str = "answer",
               reply: str | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "kind": kind, "message": "m", "standalone_question": standalone, "reply": reply,
        "answer": answer, "rewrite_usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0},
        "turn": {"question": "m", "standalone": standalone or "m", "summary": "R=0.0031"},
    }  # fmt: skip


class FakeApi:
    def __init__(self, *replies: dict[str, Any] | Exception) -> None:
        self.replies, self.bodies = list(replies), []

    def __call__(self, url: str, **kwargs: Any) -> httpx.Response:
        self.bodies.append(kwargs["json"])
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))


def ask(monkeypatch: pytest.MonkeyPatch, *replies: Any, messages: tuple[str, ...] = ("Q?",)):
    api = FakeApi(*replies)
    monkeypatch.setattr(httpx, "post", api)
    app = AppTest.from_file(APP, default_timeout=30).run()
    for message in messages:
        app.chat_input[0].set_value(message).run()
    assert not app.exception
    return app, api


def test_the_sql_is_shown_with_the_answer_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = ask(monkeypatch, chat_reply(BASE))

    assert app.code[0].value == SQL
    assert any("Data up to 2026-09-28" in caption.value for caption in app.caption)


def test_a_single_row_answer_is_shown_as_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    one_row = BASE | {"rows": [{"ANNUALIZED_VOLATILITY": 0.8101352}], "chart": None}

    app, _ = ask(monkeypatch, chat_reply(one_row))

    assert [(m.label, m.value) for m in app.metric] == [("ANNUALIZED_VOLATILITY", "0.810135")]


def test_a_declined_question_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    declined = BASE | {"status": "declined", "sql": "", "rows": [], "chart": None,
                       "explanation": "There is no stock data."}  # fmt: skip

    app, _ = ask(monkeypatch, chat_reply(declined))

    assert app.info[0].value == "There is no stock data."
    assert "no SQL" in app.code[0].value


def test_a_failed_query_shows_the_error_and_every_attempt(monkeypatch) -> None:
    attempt = {"sql": "SELECT x", "error": "invalid identifier 'X'"}
    failed = BASE | {"status": "failed", "rows": [], "chart": None, "repairs": 2,
                     "error": attempt["error"], "failed_attempts": [attempt] * 3}  # fmt: skip

    app, _ = ask(monkeypatch, chat_reply(failed))

    assert app.error[0].value == "invalid identifier 'X'"
    assert len(app.expander[0].code) == 3


def test_a_follow_up_sends_the_earlier_turn_and_shows_how_it_was_understood(monkeypatch) -> None:
    app, api = ask(
        monkeypatch,
        chat_reply(BASE),
        chat_reply(BASE, standalone="Average daily return of ETH?"),
        messages=("Average daily return of BTC?", "and ETH?"),
    )

    assert api.bodies[0] == {"message": "Average daily return of BTC?", "history": []}
    assert api.bodies[1]["message"] == "and ETH?"
    assert api.bodies[1]["history"][0]["summary"] == "R=0.0031"
    assert any("Understood as: “Average daily return of ETH?”" in c.value for c in app.caption)
    assert len(app.chat_message) == 4  # two questions, two answers


def test_a_greeting_gets_a_reply_and_no_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = ask(monkeypatch, chat_reply(None, kind="smalltalk", reply="Hi! Ask me about BTC."))

    assert any("Hi! Ask me about BTC." in m.value for m in app.markdown)
    assert not app.code


def test_one_message_is_one_paid_call_and_new_chat_clears_it(monkeypatch) -> None:
    app, api = ask(monkeypatch, chat_reply(BASE))

    assert len(api.bodies) == 1
    next(b for b in app.button if b.label == "New chat").click().run()
    assert app.session_state.chat == [] and not app.chat_message


def test_an_api_that_is_down_gives_a_hint_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = ask(monkeypatch, httpx.ConnectError("connection refused"))

    assert any("make run" in e.value for e in app.error)


def test_the_language_switch_changes_the_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "post", FakeApi())
    app = AppTest.from_file(APP, default_timeout=30).run()
    assert app.tabs[0].label == "💬 Ask"

    app.session_state.lang = "vi"
    app.run()

    assert app.tabs[0].label == "💬 Hỏi đáp"
    assert app.tabs[2].label == "📋 Watchlist & Báo cáo ngày"
