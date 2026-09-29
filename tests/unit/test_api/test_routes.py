"""Unit tests for the HTTP API, with the agent replaced by a fake (no Snowflake, no LLM)."""

import inspect
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.agents.text_to_sql import Answer
from src.api.routes import ask, get_answer_fn
from src.common.exceptions import LLMError, WarehouseError
from src.main import UNAVAILABLE, create_app
from src.services.llm import LLMUsage

SQL = "SELECT\n  trade_date,\n  close_price\nFROM FINSIGHT.MART.MART_ASSET_DAILY\nLIMIT 100"
ANSWERED = Answer(
    question="",
    sql=SQL,
    explanation="1. Keep BTC.\n2. Show closes.",
    rows=[
        {"TRADE_DATE": date(2026, 9, 1), "CLOSE_PRICE": Decimal("64000.50")},
        {"TRADE_DATE": date(2026, 9, 2), "CLOSE_PRICE": Decimal("64100.25")},
    ],
    truncated=False,
    usage=LLMUsage(input_tokens=2000, output_tokens=150, cost_usd=0.0004),
    llm_seconds=2.1,
    sql_seconds=0.8,
    retrieved=("close_price",),
    seconds=3.4,
)


def client_answering(result: Answer | Exception) -> TestClient:
    """An app whose agent returns `result` (or raises it) for any question."""

    def fake_agent(question: str) -> Answer:
        if isinstance(result, Exception):
            raise result
        return replace(result, question=question)

    app = create_app()
    app.dependency_overrides[get_answer_fn] = lambda: fake_agent
    return TestClient(app)


def post_ask(result: Answer | Exception, question: str = "BTC closes?") -> dict:
    response = client_answering(result).post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_needs_no_credentials() -> None:
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200 and response.json() == {"status": "ok"}


def test_an_answer_comes_back_as_plain_json_with_its_sql_and_a_chart() -> None:
    body = post_ask(ANSWERED)

    assert body["status"] == "answered" and body["question"] == "BTC closes?"
    assert body["sql"] == SQL  # always visible (spec §3.1)
    assert body["columns"] == ["TRADE_DATE", "CLOSE_PRICE"]
    assert body["rows"][0] == {"TRADE_DATE": "2026-09-01", "CLOSE_PRICE": 64000.5}  # not Decimal
    assert body["chart"] == {"kind": "line", "x": "TRADE_DATE", "y": ["CLOSE_PRICE"], "color": None}
    assert body["usage"] == {"input_tokens": 2000, "output_tokens": 150, "cost_usd": 0.0004}
    assert body["total_seconds"] == 3.4


def test_a_value_json_cannot_hold_becomes_null() -> None:
    body = post_ask(replace(ANSWERED, rows=[{"X": float("nan")}]))

    assert body["rows"] == [{"X": None}]


def test_the_data_cannot_answer_is_declined() -> None:
    declined = replace(ANSWERED, sql="", rows=[], explanation="There is no stock data.")

    body = post_ask(declined)

    assert body["status"] == "declined" and body["explanation"] == "There is no stock data."
    assert body["chart"] is None and body["rows"] == []


def test_a_blocked_query_still_shows_the_sql_that_was_refused() -> None:
    error = "Blocked by the SQL guard: only a SELECT query may run, got DELETE"
    blocked = replace(
        ANSWERED, sql="DELETE FROM X", rows=[], violations=("not_select",), error=error
    )

    body = post_ask(blocked)

    assert body["status"] == "blocked" and body["sql"] == "DELETE FROM X"
    assert body["violations"] == ["not_select"]


def test_a_failed_query_lists_every_attempt() -> None:
    attempts = ({"sql": "SELECT bad", "error": "invalid identifier 'BAD'"},) * 3
    failed = replace(ANSWERED, rows=[], error="invalid identifier 'BAD'", repairs=2,
                     attempts=attempts)  # fmt: skip

    body = post_ask(failed)

    assert body["status"] == "failed" and body["repairs"] == 2
    assert len(body["failed_attempts"]) == 3


@pytest.mark.parametrize("question", ["", "   ", "x" * 501], ids=["empty", "blank", "too-long"])
def test_a_bad_question_is_rejected_before_any_llm_call(question: str) -> None:
    calls: list[str] = []
    app = create_app()
    app.dependency_overrides[get_answer_fn] = lambda: calls.append

    response = TestClient(app).post("/ask", json={"question": question})

    assert response.status_code == 422 and calls == []


@pytest.mark.parametrize(
    "error",
    [LLMError("OpenAI returned 500"), WarehouseError("Could not connect: account xy12345")],
    ids=["llm-down", "snowflake-down"],
)
def test_a_service_we_depend_on_being_down_is_a_503_without_internal_details(
    error: Exception,
) -> None:
    response = client_answering(error).post("/ask", json={"question": "BTC?"})

    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}  # no account name, no driver message


def test_ask_is_a_plain_function_so_fastapi_runs_it_in_a_worker_thread() -> None:
    # answer_question blocks for seconds; inside `async def` it would freeze the whole server.
    assert not inspect.iscoroutinefunction(ask)
