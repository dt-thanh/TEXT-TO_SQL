"""Unit tests for the Research tab of the Streamlit screen, with a fake API (AppTest)."""

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
ANSWER = {
    "question": "How did ETH do?", "status": "complete",
    "findings": [{"claim": "ETH returned -10.97% in 2025.", "evidence_ids": ["ev1"]}],
    "evidence": [], "caveats": [], "plan": [], "decline_reason": "",
    "analysis_window": ["2025-01-01", "2025-12-31"], "data_as_of": "2026-10-21",
    "usage": {"input_tokens": 3000, "output_tokens": 400, "cost_usd": 0.0019},
    "llm_seconds": 3.0, "sql_seconds": 1.0, "total_seconds": 8.8, "report_markdown": REPORT,
}  # fmt: skip


def run_research(monkeypatch: pytest.MonkeyPatch, reply: dict[str, Any] | Exception) -> Any:
    calls: list[str] = []

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append(url)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(200, json=reply, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    app = AppTest.from_file(APP, default_timeout=30).run()
    app.text_area(key="research_question").input("How did ETH do?").run()
    next(b for b in app.button if b.label == "Research").click().run()
    assert not app.exception
    return app, calls


def test_one_research_click_calls_the_research_endpoint_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, calls = run_research(monkeypatch, ANSWER)

    assert len(calls) == 1 and calls[0].endswith("/research")
    assert "research_pending" not in app.session_state


def test_the_report_with_its_sql_is_shown_and_can_be_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = run_research(monkeypatch, ANSWER)

    shown = " ".join(m.value for m in app.markdown)
    assert "ETH returned -10.97% in 2025." in shown
    assert "SELECT EXP(SUM(log_return))" in shown  # the SQL is part of the report, not hidden
    assert app.success[0].value == "Status: complete"
    assert app.get("download_button")  # the Markdown report can be saved


def test_a_declined_research_question_says_why(monkeypatch: pytest.MonkeyPatch) -> None:
    report = "# Tesla?\n\n## Not answered\nNo stocks.\n"
    declined = {**ANSWER, "status": "declined", "decline_reason": "There is no stock data.",
                "findings": [], "report_markdown": report}  # fmt: skip

    app, _ = run_research(monkeypatch, declined)

    assert app.info[0].value == "Status: declined"
    assert any("There is no stock data." in m.value for m in app.markdown)


def test_the_research_tab_hints_when_the_api_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    app, _ = run_research(monkeypatch, httpx.ConnectError("connection refused"))

    assert "make run" in app.error[0].value
