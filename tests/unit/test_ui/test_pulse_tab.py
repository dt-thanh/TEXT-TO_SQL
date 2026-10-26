"""The Watchlist & Brief tab with a fake API (AppTest): statuses, adding a coin, the brief."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[3] / "ui" / "streamlit_app.py")
WATCHLISTS = {
    "default": [
        {"symbol": "BTCUSDT", "status": "ready", "data_from": "2019-01-01",
         "data_through": "2026-10-25", "error": None},
        {"symbol": "LINKUSDT", "status": "loading", "data_from": None, "data_through": None,
         "error": None},
    ]
}  # fmt: skip
HEALTH = {
    "sources": {"prices_through": "2026-10-25", "tvl_through": "2026-10-25"},
    "data_ok": True, "briefs_today": {"default": "complete"}, "assets_needing_attention": [],
    "llm_usage": {"spent_usd": 0.004, "cap_usd": 1.0},
}  # fmt: skip
BRIEF_MD = (
    "# Daily Brief: default\n\nStatus: **complete**  \n\n## Risk signals\nNo risk rule fired."
)


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        path = url.split("8000", 1)[1]
        self.calls.append((method, path, kwargs.get("json")))
        body: Any = None
        if path == "/health/data":
            body = HEALTH
        elif path == "/watchlists":
            body = WATCHLISTS
        elif path.startswith("/briefs?"):
            body = [{"brief_date": "2026-10-26"}]
        elif path.startswith("/briefs/"):
            body = {"markdown": BRIEF_MD}
        elif path == "/assets/check":
            body = [
                {"input": "arb", "symbol": "ARBUSDT", "ok": True, "action": "add",
                 "message": "on Binance: will be added"},
                {"input": "arbb", "symbol": "ARBBUSDT", "ok": False, "action": "none",
                 "message": "not a USDT spot pair trading on Binance", "suggestions": ["ARBUSDT"]},
            ]  # fmt: skip
        elif path.endswith("/add"):
            body = {"results": [{"input": "ARBUSDT", "symbol": "ARBUSDT", "ok": True,
                                 "action": "add", "message": "added: loading history"}],
                    "watchlist": []}  # fmt: skip
        elif method == "PUT":
            body = []
        elif path == "/brief":
            body = {"watchlist_name": "default", "markdown": BRIEF_MD.replace("default", "now"),
                    "seconds": 4.2, "usage": {"cost_usd": 0.0019}}  # fmt: skip
        return httpx.Response(200, json=body, request=httpx.Request(method, url))


def open_app(monkeypatch: pytest.MonkeyPatch) -> tuple[AppTest, FakeApi]:
    fake = FakeApi()
    monkeypatch.setattr(httpx, "request", fake)
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()
    assert not app.exception
    return app, fake


def test_the_watchlist_shows_each_coin_with_its_status_and_the_saved_brief(monkeypatch) -> None:
    app, _ = open_app(monkeypatch)

    table = app.dataframe[0].value
    assert list(table["asset"]) == ["BTCUSDT", "LINKUSDT"]
    assert list(table["status"]) == ["ready", "loading"]
    shown = " ".join(m.value for m in app.markdown)
    assert "No risk rule fired." in shown  # the saved morning brief
    assert any("LLM today $0.0040 of $1.00" in c.value for c in app.caption)


def test_one_click_makes_one_brief(monkeypatch) -> None:
    app, fake = open_app(monkeypatch)

    next(b for b in app.button if b.label == "Generate Daily Brief").click().run()

    posts = [c for c in fake.calls if c[0] == "POST"]
    assert posts == [
        ("POST", "/brief", {"watchlist": "default", "window_days": 30, "language": "en"})
    ]
    assert "brief_pending" not in app.session_state
    assert any(c.value.startswith("Made now · 4.2s") for c in app.caption)


def test_coins_are_checked_then_only_the_valid_ones_are_added(monkeypatch) -> None:
    app, fake = open_app(monkeypatch)

    app.text_input(key="coin_text").input("arb, arbb").run()
    next(b for b in app.button if b.label == "Check").click().run()

    table = app.dataframe[-1].value
    assert list(table["did you mean"]) == ["", "ARBUSDT"]  # the typo gets a suggestion
    next(b for b in app.button if b.label == "Add 1 valid coin(s)").click().run()

    writes = [c for c in fake.calls if c[0] == "POST" and c[1] != "/assets/check"]
    assert writes == [("POST", "/watchlists/default/add", {"text": "ARBUSDT"})]
    assert any("added: loading history" in m.value for m in app.success)


def test_without_the_api_the_tab_says_so_instead_of_crashing() -> None:
    app = AppTest.from_file(APP, default_timeout=30)
    app.run()

    assert not app.exception
    assert any("Cannot reach the API" in e.value for e in app.error)
