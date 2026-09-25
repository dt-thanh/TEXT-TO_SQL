"""Unit tests for Settings: safe defaults, hidden secrets, fail-fast validation."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.common.config import Settings
from src.common.exceptions import ConfigError


def make_settings(**overrides: object) -> Settings:
    """Build Settings from explicit values only, ignoring the developer's .env file."""

    return Settings(_env_file=None, **overrides)


def test_defaults_work_without_credentials() -> None:
    settings = make_settings()

    assert settings.snowflake_database == "FINSIGHT"
    assert settings.snowflake_warehouse == "FINSIGHT_WH"
    assert settings.snowflake_role == "FINSIGHT_ENGINEER"
    assert settings.log_level == "INFO"


def test_secrets_are_hidden_when_printed() -> None:
    settings = make_settings(fred_api_key="abc123")

    assert "abc123" not in repr(settings)
    assert settings.fred_api_key.get_secret_value() == "abc123"


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="LOUD")


def test_require_snowflake_lists_every_missing_setting() -> None:
    settings = make_settings(snowflake_account="myorg-myaccount")

    with pytest.raises(ConfigError) as exc_info:
        settings.require_snowflake()

    message = str(exc_info.value)
    assert "SNOWFLAKE_USER" in message
    assert "SNOWFLAKE_PRIVATE_KEY_PATH" in message
    assert "SNOWFLAKE_ACCOUNT" not in message


def test_require_snowflake_rejects_missing_key_file(tmp_path: Path) -> None:
    settings = make_settings(
        snowflake_account="myorg-myaccount",
        snowflake_user="FINSIGHT_SVC",
        snowflake_private_key_path=tmp_path / "missing.p8",
    )

    with pytest.raises(ConfigError, match="does not exist"):
        settings.require_snowflake()


def test_require_snowflake_passes_when_complete(tmp_path: Path) -> None:
    key_file = tmp_path / "rsa_key.p8"
    key_file.write_text("dummy")
    settings = make_settings(
        snowflake_account="myorg-myaccount",
        snowflake_user="FINSIGHT_SVC",
        snowflake_private_key_path=key_file,
    )

    settings.require_snowflake()
