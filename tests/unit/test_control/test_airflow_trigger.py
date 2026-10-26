"""Starting onboarding through Airflow is best effort (spec v1.1 DYN-12)."""

import httpx

from src.common.config import Settings
from src.control.airflow_trigger import trigger_dag

SETTINGS = Settings(
    _env_file=None,
    airflow_api_url="http://airflow:8080",
    airflow_api_user="airflow",
    airflow_api_password="secret-pw",
)


def client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://airflow:8080", transport=httpx.MockTransport(handler))


def test_a_token_then_a_dag_run() -> None:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/auth/token":
            return httpx.Response(201, json={"access_token": "tok"})
        return httpx.Response(200, json={"dag_run_id": "manual__1"})

    assert trigger_dag(settings=SETTINGS, http=client(handler)) is True
    assert seen == [
        ("POST", "/auth/token", None),
        ("POST", "/api/v2/dags/finsight_asset_onboarding/dagRuns", "Bearer tok"),
    ]


def test_airflow_down_or_refusing_is_false_and_logs_no_secret(caplog) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad credentials"})

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    assert trigger_dag(settings=SETTINGS, http=client(refused)) is False
    assert trigger_dag(settings=SETTINGS, http=client(down)) is False
    assert "secret-pw" not in caplog.text


def test_without_a_url_nothing_is_called() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("called")

    assert trigger_dag(settings=Settings(_env_file=None), http=client(handler)) is False
