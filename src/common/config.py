"""Load application configuration from environment variables and .env."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.common.exceptions import ConfigError


class Settings(BaseSettings):
    """Every setting has a safe default so the API can start without credentials."""

    snowflake_account: str = ""
    snowflake_user: str = ""
    snowflake_role: str = "FINSIGHT_ENGINEER"
    snowflake_warehouse: str = "FINSIGHT_WH"
    snowflake_database: str = "FINSIGHT"
    snowflake_private_key_path: Path | None = None
    snowflake_private_key_passphrase: SecretStr | None = None

    fred_api_key: SecretStr = SecretStr("")

    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4.1-mini"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    def require_snowflake(self) -> None:
        """Raise ConfigError naming every missing Snowflake setting."""

        required = ("snowflake_account", "snowflake_user", "snowflake_private_key_path")
        missing = [name.upper() for name in required if not getattr(self, name)]
        if missing:
            raise ConfigError(f"Missing Snowflake settings in .env: {', '.join(missing)}")
        if not self.snowflake_private_key_path.is_file():
            raise ConfigError(
                f"SNOWFLAKE_PRIVATE_KEY_PATH does not exist: {self.snowflake_private_key_path}"
            )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance for the whole process."""

    return Settings()
