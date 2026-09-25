"""Smoke-test the health and placeholder ask endpoints.

TODO: Add validation, error mapping, and real agent-response contract tests.
"""

import asyncio

import httpx

from src.main import app


async def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    """Send a request directly to the ASGI app without opening a network port.

    TODO: Move this helper into shared fixtures when more API tests are added.
    """

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_health() -> None:
    """Verify the API can start without Snowflake or LLM credentials.

    TODO: Add a separate readiness test after dependency probes exist.
    """

    response = asyncio.run(request("GET", "/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ask_is_stub() -> None:
    """Verify the placeholder ask contract remains explicit.

    TODO: Replace this assertion when /ask invokes the graph.
    """

    response = asyncio.run(request("POST", "/ask", json={"question": "Số dư hiện tại?"}))

    assert response.status_code == 200
    assert response.json()["status"] == "stub"
