"""Unit tests for BinanceClient. httpx.MockTransport replaces the network entirely."""

import httpx
import pytest

from src.common.exceptions import SourceAPIError
from src.ingestion.binance.client import BinanceClient

ROW = [
    1704067200000, "42283.58", "42554.57", "42261.02", "42475.23", "1271.68",
    1704070799999, "53957180.84", 47134, "682.57", "28971975.95", "0",
]  # fmt: skip


def make_client(
    outcomes: list[httpx.Response | Exception],
) -> tuple[BinanceClient, list[httpx.Request], list[float]]:
    """Client whose HTTP layer replays `outcomes` in order, recording requests and sleeps."""

    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    queue = list(outcomes)

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        outcome = queue.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://binance.test")
    client = BinanceClient(http=http, max_attempts=3, sleep=sleeps.append)
    return client, requests, sleeps


def get_btc(client: BinanceClient) -> list[list[object]]:
    return client.get_klines("BTCUSDT", "1h", start_ms=1, end_ms=2)


def test_sends_kline_query_and_returns_rows() -> None:
    client, requests, sleeps = make_client([httpx.Response(200, json=[ROW])])

    assert get_btc(client) == [ROW]
    assert requests[0].url.path == "/api/v3/klines"
    assert dict(requests[0].url.params) == {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "startTime": "1",
        "endTime": "2",
        "limit": "1000",
    }
    assert sleeps == []


def test_rate_limit_waits_as_long_as_binance_asks() -> None:
    client, _, sleeps = make_client(
        [httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, json=[ROW])]
    )

    assert get_btc(client) == [ROW]
    assert sleeps == [7.0]


def test_server_errors_back_off_exponentially() -> None:
    client, _, sleeps = make_client(
        [httpx.Response(503), httpx.Response(502), httpx.Response(200, json=[])]
    )

    assert get_btc(client) == []
    assert sleeps == [1.0, 2.0]


def test_network_errors_are_retried() -> None:
    client, requests, sleeps = make_client(
        [httpx.ConnectError("connection refused"), httpx.Response(200, json=[ROW])]
    )

    assert get_btc(client) == [ROW]
    assert len(requests) == 2
    assert sleeps == [1.0]


def test_invalid_symbol_fails_at_once_with_binance_message() -> None:
    client, requests, sleeps = make_client(
        [httpx.Response(400, json={"code": -1121, "msg": "Invalid symbol."})]
    )

    with pytest.raises(SourceAPIError, match="Invalid symbol"):
        get_btc(client)
    assert len(requests) == 1
    assert sleeps == []


def test_ip_ban_is_not_retried() -> None:
    client, requests, _ = make_client([httpx.Response(418, headers={"Retry-After": "120"})])

    with pytest.raises(SourceAPIError, match="HTTP 418"):
        get_btc(client)
    assert len(requests) == 1


def test_gives_up_after_max_attempts() -> None:
    client, requests, sleeps = make_client([httpx.Response(503)] * 3)

    with pytest.raises(SourceAPIError, match="after 3 attempts"):
        get_btc(client)
    assert len(requests) == 3
    assert sleeps == [1.0, 2.0]
