"""Unit tests for FredClient: request shape, and above all that the API key never leaks."""

from datetime import date

import httpx
import pytest

from src.common.exceptions import ConfigError, SourceAPIError
from src.ingestion.fred.client import FredClient

API_KEY = "abcdefghijklmnopqrstuvwxyz123456"


def make_client(
    outcomes: list[httpx.Response | Exception],
) -> tuple[FredClient, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    queue = list(outcomes)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://fred.test")
    return FredClient(http=http, api_key=API_KEY, max_attempts=2, sleep=lambda s: None), requests


def get_dgs10(client: FredClient) -> dict[str, object]:
    return client.get_observation_changes(
        "DGS10", date(2018, 12, 1), date(2024, 1, 1), date(2024, 12, 31)
    )


def test_asks_for_new_and_revised_values_with_the_key() -> None:
    client, requests = make_client([httpx.Response(200, json={"observations": []})])

    get_dgs10(client)

    params = dict(requests[0].url.params)
    assert requests[0].url.path == "/series/observations"
    assert params["output_type"] == "3"
    assert params["observation_start"] == "2018-12-01"
    assert (params["realtime_start"], params["realtime_end"]) == ("2024-01-01", "2024-12-31")
    assert params["api_key"] == API_KEY
    assert params["file_type"] == "json"


def test_error_messages_never_contain_the_key_or_url() -> None:
    body = {"error_code": 400, "error_message": f"Bad Request. api_key={API_KEY} rejected"}
    client, _ = make_client([httpx.Response(400, json=body)])

    with pytest.raises(SourceAPIError) as exc_info:
        get_dgs10(client)

    message = str(exc_info.value)
    assert API_KEY not in message
    assert "***" in message
    assert "https://" not in message


def test_network_errors_are_masked_too() -> None:
    client, _ = make_client(
        [httpx.ConnectError(f"cannot reach ?api_key={API_KEY}")] * 2,
    )

    with pytest.raises(SourceAPIError) as exc_info:
        get_dgs10(client)

    assert API_KEY not in str(exc_info.value)


def test_missing_key_fails_before_any_request() -> None:
    with pytest.raises(ConfigError, match="FRED_API_KEY"):
        FredClient(api_key="")
