"""Unit tests for get_json, the retry policy every source shares."""

import httpx
import pytest

from src.common.exceptions import SourceAPIError
from src.ingestion.retrying_http import get_json

MAINTENANCE_PAGE = "<!doctype html><title>Site Maintenance</title>"


def call(outcomes: list[httpx.Response], max_attempts: int = 3) -> tuple[object, list[float]]:
    queue = list(outcomes)
    waits: list[float] = []
    http = httpx.Client(
        transport=httpx.MockTransport(lambda request: queue.pop(0)), base_url="https://api.test"
    )
    result = get_json(
        http, "/data", {}, source="TEST", max_attempts=max_attempts, sleep=waits.append
    )
    return result, waits


def html(status: int = 200) -> httpx.Response:
    return httpx.Response(status, text=MAINTENANCE_PAGE, headers={"content-type": "text/html"})


def test_a_maintenance_page_served_with_200_is_retried() -> None:
    result, waits = call([html(), httpx.Response(200, json={"ok": True})])

    assert result == {"ok": True}
    assert waits == [1.0]


def test_a_maintenance_page_that_never_ends_is_a_clean_source_error() -> None:
    with pytest.raises(SourceAPIError, match="HTTP 200 without JSON") as exc_info:
        call([html()] * 3)

    assert "text/html" in str(exc_info.value)


def test_429_waits_as_long_as_the_server_asks() -> None:
    limited = httpx.Response(429, headers={"Retry-After": "7"})

    result, waits = call([limited, httpx.Response(200, json=[1])])

    assert result == [1]
    assert waits == [7.0]


def test_a_bad_request_is_not_retried() -> None:
    with pytest.raises(SourceAPIError, match="HTTP 400"):
        call([httpx.Response(400, text="bad parameter"), httpx.Response(200, json={})])
