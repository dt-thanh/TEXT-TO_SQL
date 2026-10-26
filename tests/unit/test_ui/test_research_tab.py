"""The Research report tab: a conversation whose answers are reports (AppTest, fake API)."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[3] / "ui" / "streamlit_app.py")
REPORT = (
    "# How did ETH do?\n\nStatus: **complete**  \n\n## Findings\n"
    "- ETH returned -10.97% in 2025. [ev1]\n\n## Evidence\n### ev1: Return over a period\n"
    "```sql\nSELECT EXP(SUM(log_return)) - 1 AS period_return\n```\n\n## Caveats\n"
    "- Data up to 2026-10-21 (UTC); today is not included.\n"
)
RESEARCH = {
    "question": "How did ETH do?", "status": "complete",
    "findings": [{"claim": "ETH returned -10.97% in 2025.", "evidence_ids": ["ev1"]}],
    "evidence": [], "caveats": [], "plan": [], "decline_reason": "",
    "analysis_window": ["2025-01-01", "2025-12-31"], "data_as_of": "2026-10-21",
    "usage": {"input_tokens": 3000, "output_tokens": 400, "cost_usd": 0.0019},
    "llm_seconds": 3.0, "sql_seconds": 1.0, "total_seconds": 8.8, "timings": {},
    "report_markdown": REPORT,
}  # fmt: skip


def reply(standalone: str | None = None) -> dict[str, Any]:
    return {
        "kind": "answer", "message": "m", "standalone_question": standalone, "reply": None,
        "research": RESEARCH,
        "rewrite_usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        "turn": {"question": "m", "standalone": standalone or "m",
                 "summary": "ETH returned -10.97% in 2025."},
    }  # fmt: skip


def run(monkeypatch: pytest.MonkeyPatch, *messages: str, replies: list[Any]) -> tuple:
    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append((url, kwargs["json"]))
        answer = replies.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, json=answer, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    app = AppTest.from_file(APP, default_timeout=30).run()
    for message in messages:
        app.chat_input(key="research_chat_input").set_value(message).run()
    assert not app.exception
    return app, calls


def test_a_question_calls_the_research_chat_once_and_shows_the_report(monkeypatch) -> None:
    app, calls = run(monkeypatch, "How did ETH do in 2025?", replies=[reply()])

    assert len(calls) == 1 and calls[0][0].endswith("/research/chat")
    shown = " ".join(m.value for m in app.markdown)
    assert "ETH returned -10.97% in 2025." in shown
    assert "SELECT EXP(SUM(log_return))" in shown  # the SQL is part of the report, not hidden


def test_a_follow_up_is_sent_with_the_earlier_report(monkeypatch) -> None:
    app, calls = run(
        monkeypatch, "How did ETH do in 2025?", "and BTC?",
        replies=[reply(), reply(standalone="How did BTC do in 2025?")],
    )  # fmt: skip

    assert calls[1][1]["history"][0]["summary"] == "ETH returned -10.97% in 2025."
    assert any("Understood as: “How did BTC do in 2025?”" in c.value for c in app.caption)


def test_suggested_questions_replace_the_old_dropdown(monkeypatch) -> None:
    app, calls = run(monkeypatch, replies=[reply()])

    assert not app.selectbox  # no "example questions" dropdown any more
    example = next(b for b in app.button if b.key == "research_chat_example_0")
    example.click().run()
    assert len(calls) == 1 and calls[0][1]["message"] == example.label


def test_every_tab_opens_with_a_guide(monkeypatch) -> None:
    app, _ = run(monkeypatch, replies=[])

    guides = [m.value for m in app.markdown if m.value.startswith("**What it is for:**")]
    assert len(guides) == 3
