"""API tests run with open access and an unlimited budget unless a test says otherwise."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from src import main
from src.api import pulse
from src.api.security import LIMITS
from src.common.config import get_settings


class UnlimitedCap:
    def __init__(self) -> None:
        self.recorded: list[float] = []

    @contextmanager
    def reserve(self, max_cost_usd: float) -> Iterator:
        yield self.recorded.append

    def status(self) -> dict[str, float]:
        return {"spent_usd": sum(self.recorded), "reserved_usd": 0.0, "cap_usd": 1.0,
                "remaining_usd": 1.0 - sum(self.recorded)}  # fmt: skip


@pytest.fixture(autouse=True)
def open_access_and_budget(monkeypatch: pytest.MonkeyPatch) -> Iterator[UnlimitedCap]:
    monkeypatch.setenv("AUTH_MODE", "local")
    get_settings.cache_clear()
    cap = UnlimitedCap()
    monkeypatch.setattr(pulse, "cost_cap", lambda: cap)
    monkeypatch.setattr(main, "write_request_log", lambda row: None)  # no Snowflake rows
    for limiter in LIMITS.values():
        limiter._calls.clear()
    yield cap
    get_settings.cache_clear()
