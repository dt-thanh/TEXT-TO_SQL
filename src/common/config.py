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

    # The API writes watchlists, asset requests and usage as its own user with FINSIGHT_APP:
    # rows of the CONTROL schema only (infra/snowflake/03_control_access.sql).
    snowflake_app_user: str = ""
    snowflake_app_role: str = "FINSIGHT_APP"
    snowflake_app_private_key_path: Path | None = None

    # Airflow's REST API, to start asset onboarding right after a request. Empty URL: no
    # trigger, the daily fallback run picks the request up.
    airflow_api_url: str = ""
    airflow_api_user: str = ""
    airflow_api_password: SecretStr = SecretStr("")

    # local: API and UI listen on 127.0.0.1 only, no key. deployed: every request except
    # /health needs X-API-Key = FINSIGHT_SERVICE_KEY, and the API refuses to start without it.
    auth_mode: Literal["local", "deployed"] = "local"
    finsight_service_key: SecretStr = SecretStr("")
    # All LLM calls of one UTC day together (API and scheduled briefs) stop at this many USD.
    llm_daily_cost_cap_usd: float = 1.0
    # Language of the scheduled daily brief.
    brief_language: Literal["en", "vi"] = "en"

    binance_base_url: str = "https://api.binance.com"

    fred_api_key: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    # Chosen by an A/B benchmark (docs/upgrade_baseline.md, 2026-10-22): same holdout score as
    # gpt-4o-mini, steadier and about 3x faster at p95, for about twice the price per question.
    llm_model: str = "gpt-4.1-mini"
    # USD per 1M tokens, only used to report what each question cost. They must match llm_model:
    # these are gpt-4.1-mini's standard prices (developers.openai.com/api/docs/pricing, Oct 2026).
    llm_input_usd_per_1m: float = 0.40
    llm_output_usd_per_1m: float = 1.60
    # Only for reasoning models (e.g. gpt-5-mini), which reject temperature=0: "minimal", "low",
    # "medium" or "high". Empty = a non-reasoning model called at temperature 0.
    llm_reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["text", "json"] = "text"

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

        return self._as_service_user("agent")

    def for_app(self) -> "Settings":
        """The same settings, but connecting as the API's CONTROL-only user."""

        return self._as_service_user("app")

    def _as_service_user(self, who: Literal["agent", "app"]) -> "Settings":
        names = (f"snowflake_{who}_user", f"snowflake_{who}_private_key_path")
        missing = [name.upper() for name in names if not getattr(self, name)]
        if missing:
            raise ConfigError(f"Missing {who} Snowflake settings in .env: {', '.join(missing)}")
        return self.model_copy(
            update={
                "snowflake_user": getattr(self, f"snowflake_{who}_user"),
                "snowflake_role": getattr(self, f"snowflake_{who}_role"),
                "snowflake_private_key_path": getattr(self, f"snowflake_{who}_private_key_path"),
                "snowflake_private_key_passphrase": None,
            }
        )


@lru_cache
def get_settings() -> Settings:
    """Return one cached Settings instance for the whole process."""

    return Settings()
