"""Unit tests for POST /research, with research mode replaced by a fake (no Snowflake, no LLM)."""

import inspect
from dataclasses import replace
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.agents.research.workflow import ResearchAnswer
from src.api.routes import get_research_fn, research
from src.common.exceptions import LLMError
from src.main import UNAVAILABLE, create_app
from src.services.llm import LLMUsage

EVIDENCE = {
    "id": "ev1", "metric_id": "period_return", "metric_name": "Return over a period",
    "definition": "Compounded change.", "params": {"symbol": "ETHUSDT", "start_date": "2025-01-01",
    "end_date": "2025-12-31"}, "sql": "SELECT ...", "sources": ["binance"],
    "data_window": "2025-01-01..2025-12-31", "n": 365, "pit_mode": "as_known", "usable": True,
    "values": [{"column": "PERIOD_RETURN", "value": -0.1097, "unit": "fraction",
                "description": "Compounded return over the period."}],
}  # fmt: skip
ANSWER = ResearchAnswer(
    question="",
    status="complete",
    findings=[{"claim": "ETH returned -10.97% in 2025.", "evidence_ids": ["ev1"]}],
    evidence=[EVIDENCE],
    caveats=["Data up to 2026-10-21 (UTC); today is not included."],
    plan=[{"metric_id": "period_return", "params": EVIDENCE["params"], "status": "done",
           "reason": None}],  # fmt: skip
    usage=LLMUsage(3000, 400, 0.0019),
    seconds=8.8,
    data_as_of=date(2026, 10, 21),
)


def client_answering(result: ResearchAnswer | Exception) -> TestClient:
    def fake_research(question: str) -> ResearchAnswer:
        if isinstance(result, Exception):
            raise result
        return replace(result, question=question)

    app = create_app()
    app.dependency_overrides[get_research_fn] = lambda: fake_research
    return TestClient(app)


def test_a_research_answer_comes_back_with_its_evidence_sql_and_a_report() -> None:
    response = client_answering(ANSWER).post("/research", json={"question": "ETH in 2025?"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["findings"][0]["evidence_ids"] == ["ev1"]
    assert body["evidence"][0]["sql"] == "SELECT ..."
    assert body["analysis_window"] == ["2025-01-01", "2025-12-31"]
    assert body["report_markdown"].startswith("# ETH in 2025?")


def test_a_declined_research_question_says_why() -> None:
    declined = replace(
        ANSWER, status="declined", findings=[], evidence=[], plan=[], decline_reason="No stocks."
    )

    body = client_answering(declined).post("/research", json={"question": "Tesla?"}).json()

    assert body["status"] == "declined" and body["decline_reason"] == "No stocks."


@pytest.mark.parametrize("question", ["", "x" * 501])
def test_a_bad_research_question_is_rejected_before_any_call(question: str) -> None:
    calls: list[str] = []
    app = create_app()
    app.dependency_overrides[get_research_fn] = lambda: calls.append

    response = TestClient(app).post("/research", json={"question": question})

    assert response.status_code == 422 and calls == []


def test_a_service_being_down_is_a_503_without_details() -> None:
    response = client_answering(LLMError("OpenAI returned 500")).post(
        "/research", json={"question": "ETH?"}
    )

    assert response.status_code == 503 and response.json() == {"detail": UNAVAILABLE}


def test_research_is_a_plain_function_so_fastapi_runs_it_in_a_worker_thread() -> None:
    assert not inspect.iscoroutinefunction(research)
