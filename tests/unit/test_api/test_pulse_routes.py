"""Pulse endpoints and the single-owner protections (spec v1.1 SEC-01..03, PROD-01, PROD-02)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.agents.research.brief import BriefAnswer
from src.agents.research.workflow import ResearchAnswer
from src.api import pulse
from src.api.routes import get_answer_fn
from src.common.config import get_settings
from src.common.exceptions import ConfigError, WarehouseError
from src.main import create_app
from src.services.llm import LLMUsage
from tests.unit.test_api.test_routes import ANSWERED
from tests.unit.test_control.test_assets import FakeWarehouse

UNIVERSE_ROW = {"SYMBOL": "BTCUSDT", "STATUS": "ready", "DATA_FROM": date(2019, 1, 1),
                "DATA_THROUGH": date(2026, 10, 25)}  # fmt: skip


class FakeAgent:
    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        if "INFORMATION_SCHEMA" in sql:
            return [{"TABLE_NAME": "MART_ASSET_UNIVERSE", "TABLE_COMMENT": "",
                     "COLUMN_NAME": "X", "DATA_TYPE": "TEXT", "COLUMN_COMMENT": "",
                     "LATEST_TRADE_DATE": None}]  # fmt: skip
        if "MART_ASSET_UNIVERSE" in sql:
            return [UNIVERSE_ROW]
        return [{"PRICES_THROUGH": date(2026, 10, 25)}]


def brief_answer(symbols: list[str], window: int, name: str | None, language: str, use_llm: bool):
    research = ResearchAnswer("q", "complete", [], [], [], [], usage=LLMUsage(10, 5, 0.0012))
    return BriefAnswer(research, name, tuple(symbols), (), window, None, None, (), language,
                       use_llm, "complete", markdown="# brief")  # fmt: skip


def app_with(control: FakeWarehouse | None = None, triggered: list | None = None) -> TestClient:
    app = create_app()
    control = control or FakeWarehouse()
    app.dependency_overrides[pulse.get_control] = lambda: control
    app.dependency_overrides[pulse.get_agent] = FakeAgent
    app.dependency_overrides[pulse.get_brief_fn] = lambda: brief_answer
    app.dependency_overrides[pulse.get_trigger] = lambda: (
        lambda: (triggered.append(1) if triggered is not None else None) or True
    )
    app.dependency_overrides[get_answer_fn] = lambda: lambda question: ANSWERED
    return TestClient(app)


def test_adding_an_unknown_coin_is_refused_and_nothing_is_saved() -> None:
    # DYN-01 through the API: 422, no registry row, no watchlist change, no DAG run.
    control, triggered = FakeWarehouse(), []

    response = app_with(control, triggered).put("/watchlists/defi", json={"symbols": ["NOPE"]})

    assert response.status_code == 422 and "not a USDT spot pair" in response.json()["detail"]
    assert not any(sql.lstrip().startswith(("MERGE", "DELETE")) for sql, _ in control.calls)
    assert triggered == []


def test_adding_a_new_coin_requests_it_starts_onboarding_and_shows_loading() -> None:
    control = FakeWarehouse(
        {
            "CONTROL.BINANCE_SYMBOL WHERE": [{"SYMBOL": "LINKUSDT", "BASE_ASSET": "LINK"}],
            "COUNT_IF": [{"ACTIVE": 0, "REQUESTED_TODAY": 0}],
            "SELECT symbol, status, last_error": [{"SYMBOL": "LINKUSDT", "STATUS": "requested",
                                                   "LAST_ERROR": None}],
        }
    )  # fmt: skip
    triggered: list = []

    response = app_with(control, triggered).put(
        "/watchlists/defi", json={"symbols": ["btc", "link"]}
    )

    assert response.status_code == 200
    assert [(a["symbol"], a["status"]) for a in response.json()] == [
        ("BTCUSDT", "ready"),
        ("LINKUSDT", "loading"),
    ]
    assert triggered == [1]


def test_limit_errors_have_their_own_status_codes() -> None:
    control = FakeWarehouse(
        {
            "FROM FINSIGHT.CONTROL.BINANCE_SYMBOL WHERE": [
                {"SYMBOL": "LINKUSDT", "BASE_ASSET": "LINK"}
            ],
            "COUNT_IF": [{"ACTIVE": 16, "REQUESTED_TODAY": 0}],
        }
    )

    assert app_with(control).put("/watchlists/x", json={"symbols": ["LINK"]}).status_code == 409
    assert app_with().put("/watchlists/x", json={"symbols": []}).status_code == 422
    assert app_with().put("/watchlists/bad name", json={"symbols": ["BTC"]}).status_code == 422


def test_a_brief_for_a_watchlist_is_made_recorded_and_saved(open_access_and_budget) -> None:
    control = FakeWarehouse()

    response = app_with(control).post("/brief", json={"watchlist": "default"})

    assert response.status_code == 200 and response.json()["status"] == "complete"
    assert open_access_and_budget.recorded == [0.0012]
    assert control.statements("MERGE INTO FINSIGHT.CONTROL.DAILY_BRIEF")


def test_past_the_daily_budget_llm_routes_answer_429_without_running(monkeypatch) -> None:
    # SEC-02
    from src.control.usage import CostCap

    spent = FakeWarehouse({"SELECT llm_cost_usd": [{"LLM_COST_USD": 1.0}]})
    monkeypatch.setattr(pulse, "cost_cap", lambda: CostCap(spent, 1.0))
    ran: list[str] = []
    client = app_with()
    client.app.dependency_overrides[get_answer_fn] = lambda: lambda q: ran.append(q) or ANSWERED

    for path, body in (("/ask", {"question": "BTC?"}), ("/brief", {"symbols": ["BTC"]})):
        response = client.post(path, json=body)
        assert response.status_code == 429 and "daily LLM budget" in response.json()["detail"]
    assert ran == []
    # Without the LLM a brief costs nothing and still runs.
    assert client.post("/brief", json={"symbols": ["BTC"], "use_llm": False}).status_code == 200


def test_rate_limits_answer_429_with_retry_after() -> None:
    client = app_with()
    codes = [client.post("/brief", json={"symbols": ["BTC"]}).status_code for _ in range(7)]

    assert codes == [200] * 6 + [429]
    response = client.post("/brief", json={"symbols": ["BTC"]})
    assert int(response.headers["Retry-After"]) >= 1


@pytest.fixture
def deployed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_MODE", "deployed")
    monkeypatch.setenv("FINSIGHT_SERVICE_KEY", "s3cret-key")
    get_settings.cache_clear()


def test_deployed_mode_needs_the_service_key(deployed) -> None:
    # SEC-01
    client = app_with()

    assert client.get("/health").status_code == 200  # public
    assert client.post("/ask", json={"question": "BTC?"}).status_code == 401
    wrong = client.post("/ask", json={"question": "BTC?"}, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401 and wrong.json() == {"detail": "missing or wrong API key"}
    assert client.get("/usage/today", headers={"X-API-Key": "nope"}).status_code == 401
    right = client.post("/ask", json={"question": "BTC?"}, headers={"X-API-Key": "s3cret-key"})
    assert right.status_code == 200


def test_deployed_mode_without_a_key_refuses_to_start(monkeypatch) -> None:
    from src.common.config import Settings

    settings = Settings(_env_file=None, auth_mode="deployed")
    monkeypatch.setattr("src.main.get_settings", lambda: settings)

    with pytest.raises(ConfigError, match="refusing to start"):
        create_app()


def test_local_mode_needs_no_key() -> None:
    assert app_with().post("/ask", json={"question": "BTC?"}).status_code == 200


def test_every_response_has_a_request_id_and_keeps_a_safe_one() -> None:
    client = app_with()

    given = client.get("/health", headers={"X-Request-ID": "trace-123"})
    unsafe = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline"})

    assert given.headers["X-Request-ID"] == "trace-123"
    assert len(unsafe.headers["X-Request-ID"]) == 32  # replaced, never logged as given


def test_ten_requests_at_once_each_get_an_answer_and_their_own_id() -> None:
    # PROD-01, with fakes: the shared app and clients are safe across worker threads.
    client = app_with()

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(
            pool.map(lambda i: client.post("/ask", json={"question": f"BTC {i}?"}), range(10))
        )

    assert {r.status_code for r in responses} == {200}
    assert len({r.headers["X-Request-ID"] for r in responses}) == 10


def test_a_snowflake_outage_is_503_without_details() -> None:
    # PROD-02
    class DownControl:
        def execute(self, *args: Any, **kwargs: Any) -> list[Any]:
            raise WarehouseError("Could not connect: account xy123.eu, user FINSIGHT_APP_SVC")

    client = app_with()
    client.app.dependency_overrides[pulse.get_control] = DownControl

    response = client.get("/watchlists")

    assert response.status_code == 503
    assert "FINSIGHT_APP_SVC" not in response.text and "xy123" not in response.text


def test_adding_typed_coins_adds_the_right_ones_and_reports_the_wrong_one() -> None:
    control = FakeWarehouse(
        {
            "SELECT symbol, base_asset FROM FINSIGHT.CONTROL.BINANCE_SYMBOL": [
                {"SYMBOL": "ARBUSDT", "BASE_ASSET": "ARB"}
            ],
            "CONTROL.BINANCE_SYMBOL WHERE": [{"SYMBOL": "ARBUSDT", "BASE_ASSET": "ARB"}],
            "COUNT_IF": [{"ACTIVE": 0, "REQUESTED_TODAY": 0}],
        }
    )
    triggered: list = []

    response = app_with(control, triggered).post("/watchlists/defi/add", json={"text": "arb, arbb"})

    assert response.status_code == 200
    results = {r["input"]: (r["ok"], r["message"]) for r in response.json()["results"]}
    assert results["arb"] == (True, "added: loading history (a few minutes)")
    assert results["arbb"][0] is False
    [(_, params)] = control.statements("MERGE INTO FINSIGHT.CONTROL.WATCHLIST")
    assert params["s0"] == "ARBUSDT" and "s1" not in params  # only the right coin saved
    assert triggered == [1]


def test_chat_answers_and_hands_back_the_turn_to_keep(monkeypatch) -> None:
    client = app_with()

    first = client.post("/chat", json={"message": "BTC?", "history": []}).json()
    hello = client.post("/chat", json={"message": "chào bạn", "history": [first["turn"]]}).json()

    assert first["kind"] == "answer" and first["answer"]["status"] == "answered"
    assert first["turn"]["standalone"] == "BTC?"
    assert hello["kind"] == "smalltalk" and hello["answer"] is None and "Chào bạn" in hello["reply"]


def test_research_chat_rewrites_follow_ups_and_answers_with_a_report() -> None:
    from src.agents.research.workflow import ResearchAnswer
    from src.api.routes import get_research_fn

    asked: list[str] = []

    def research(question: str) -> ResearchAnswer:
        asked.append(question)
        findings = [{"claim": "ETH returned -10.97% in 2025.", "evidence_ids": ["ev1"]}]
        return ResearchAnswer(question, "complete", findings, [], [], [],
                              usage=LLMUsage(1000, 100, 0.0015))  # fmt: skip

    client = app_with()
    client.app.dependency_overrides[get_research_fn] = lambda: research

    first = client.post("/research/chat", json={"message": "How did ETH do in 2025?"}).json()
    advice = client.post("/research/chat", json={"message": "should I buy ETH?",
                                                 "history": [first["turn"]]}).json()  # fmt: skip

    assert first["kind"] == "answer" and first["research"]["status"] == "complete"
    assert first["turn"]["summary"] == "ETH returned -10.97% in 2025."
    assert advice["kind"] == "declined" and advice["research"] is None
    assert asked == ["How did ETH do in 2025?"]  # the advice request never reached research
