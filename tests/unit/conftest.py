"""Shared fixtures for unit tests."""

import os

import pytest

PROJECT_ENV_PREFIXES = (
    "SNOWFLAKE_",
    "FRED_",
    "OPENAI_",
    "LLM_",
    "LOG_",
    "AIRFLOW_API_",
    "AUTH_",
    "FINSIGHT_",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hide the developer's real environment so tests only see values they set."""

    for key in list(os.environ):
        if key.startswith(PROJECT_ENV_PREFIXES):
            monkeypatch.delenv(key)
