"""Unit tests for SnowflakeClient. The real driver is replaced, so no network is used."""

from pathlib import Path
from typing import Any

import pytest
import snowflake.connector
from snowflake.connector.errors import DatabaseError, ProgrammingError

from src.common.config import Settings
from src.common.exceptions import ConfigError, WarehouseError
from src.services.snowflake_client import SnowflakeClient


class FakeCursor:
    """Stands in for a Snowflake DictCursor."""

    def __init__(self, rows: list[dict[str, Any]], error: Exception | None = None) -> None:
        self.rows = rows
        self.error = error
        self.executed: list[tuple[str, Any]] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        pass

    def execute(self, sql: str, params: Any = None) -> None:
        self.executed.append((sql, params))
        if self.error:
            raise self.error

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    """Stands in for a SnowflakeConnection and remembers whether it was closed."""

    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def cursor(self, cursor_class: Any = None) -> FakeCursor:
        return self._cursor


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    key_file = tmp_path / "rsa_key.p8"
    key_file.write_text("not-a-real-key")
    return Settings(
        _env_file=None,
        snowflake_account="myorg-myaccount",
        snowflake_user="FINSIGHT_SVC",
        snowflake_private_key_path=key_file,
    )


def test_connect_fails_fast_without_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kw: calls.append(kw))

    with pytest.raises(ConfigError):
        SnowflakeClient(Settings(_env_file=None)).connect()

    assert calls == []


def test_connect_uses_key_pair_auth(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    captured: dict[str, Any] = {}

    def fake_connect(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "fake-connection"

    monkeypatch.setattr(snowflake.connector, "connect", fake_connect)

    assert SnowflakeClient(settings).connect() == "fake-connection"
    assert captured["account"] == "myorg-myaccount"
    assert captured["user"] == "FINSIGHT_SVC"
    assert captured["role"] == "FINSIGHT_ENGINEER"
    assert captured["warehouse"] == "FINSIGHT_WH"
    assert captured["database"] == "FINSIGHT"
    assert captured["private_key_file"] == str(settings.snowflake_private_key_path)
    assert "password" not in captured


def test_connect_wraps_driver_errors(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    def fake_connect(**kwargs: Any) -> None:
        raise DatabaseError("250001: Could not connect to Snowflake backend")

    monkeypatch.setattr(snowflake.connector, "connect", fake_connect)

    with pytest.raises(WarehouseError) as exc_info:
        SnowflakeClient(settings).connect()

    assert isinstance(exc_info.value.__cause__, DatabaseError)


def test_execute_returns_rows_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    cursor = FakeCursor(rows=[{"ROLE_NAME": "FINSIGHT_ENGINEER"}])
    connection = FakeConnection(cursor)
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kw: connection)

    rows = SnowflakeClient(settings).execute("SELECT CURRENT_ROLE() AS role_name")

    assert rows == [{"ROLE_NAME": "FINSIGHT_ENGINEER"}]
    assert cursor.executed == [("SELECT CURRENT_ROLE() AS role_name", None)]
    assert connection.closed is True


def test_execute_wraps_query_errors(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    cursor = FakeCursor(rows=[], error=ProgrammingError("SQL compilation error"))
    connection = FakeConnection(cursor)
    monkeypatch.setattr(snowflake.connector, "connect", lambda **kw: connection)

    with pytest.raises(WarehouseError):
        SnowflakeClient(settings).execute("SELECT nope")

    assert connection.closed is True
