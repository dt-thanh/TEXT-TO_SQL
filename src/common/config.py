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

    # The Text-to-SQL agent connects as its own user with the read-only FINSIGHT_AGENT role,
    # so LLM-written SQL can only ever SELECT from MART (infra/snowflake/02_agent_user.sql).
    snowflake_agent_user: str = ""
    snowflake_agent_role: str = "FINSIGHT_AGENT"
    snowflake_agent_private_key_path: Path | None = None

    binance_base_url: str = "https://api.binance.com"

    fred_api_key: SecretStr = SecretStr("")

    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: SecretStr = SecretStr("")
    anthropic_api_key: SecretStr = SecretStr("")
    llm_model: str = "gpt-4.1-mini"
    # USD per 1M tokens, only used to log what each question cost. Defaults are gpt-4o-mini's
    # standard prices (developers.openai.com/api/docs/pricing, Sep 2026); update if you switch.
    llm_input_usd_per_1m: float = 0.15
    llm_output_usd_per_1m: float = 0.60

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

    def for_agent(self) -> "Settings":
        """The same settings, but connecting as the read-only Text-to-SQL agent user."""

        missing = [
            name.upper()
            for name in ("snowflake_agent_user", "snowflake_agent_private_key_path")
            if not getattr(self, name)
        ]
        if missing:
            raise ConfigError(f"Missing agent Snowflake settings in .env: {', '.join(missing)}")
        return self.model_copy(
            update={
                "snowflake_user": self.snowflake_agent_user,
                "snowflake_role": self.snowflake_agent_role,
                "snowflake_private_key_path": self.snowflake_agent_private_key_path,
                "snowflake_private_key_passphrase": None,
            }
        )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance for the whole process."""

    return Settings()
