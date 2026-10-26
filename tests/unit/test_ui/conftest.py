"""UI tests never reach a real API: every httpx.request goes to a fake unless a test sets one."""

from typing import Any

import httpx
import pytest
import streamlit as st


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(method: str, url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("no API in unit tests")

    monkeypatch.setattr(httpx, "request", unreachable)
    monkeypatch.setenv("FINSIGHT_UI_LANGUAGE", "en")  # the tests read English labels
    st.cache_data.clear()  # cached GETs must not leak from one test into the next
