"""Unit tests for the Text-to-SQL loop, with a fake LLM and a fake warehouse."""

from datetime import date
from pathlib import Path
from typing import Any

import pytest

from src.agents.text_to_sql import answer_question, build_user_prompt, system_prompt
from src.agents.tools.schema_tools import format_schema_context, table_names
from src.common.config import Settings
from src.common.exceptions import ConfigError, WarehouseError
from src.services.llm import LLMResult, LLMUsage

USAGE = LLMUsage(input_tokens=1500, output_tokens=120, cost_usd=0.0003)
ASSET = "FINSIGHT.MART.MART_ASSET_DAILY"  # the only table in METADATA, so the only one allowed
METADATA = [
    {"TABLE_NAME": "MART_ASSET_DAILY", "TABLE_COMMENT": "One row per asset per day.",
     "COLUMN_NAME": "SYMBOL", "DATA_TYPE": "TEXT", "COLUMN_COMMENT": "Binance pair."},
    {"TABLE_NAME": "MART_ASSET_DAILY", "TABLE_COMMENT": "One row per asset per day.",
     "COLUMN_NAME": "CLOSE_PRICE", "DATA_TYPE": "NUMBER", "COLUMN_COMMENT": ""},
]  # fmt: skip


class FakeLLM:
    def __init__(self, sql: str, explanation: str = "1. Do it.") -> None:
        self.data = {"sql": sql, "explanation": explanation}
        self.prompts: list[str] = []

    def generate_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResult:
        self.prompts.append(user_prompt)
        return LLMResult(self.data, USAGE, "gpt-4o-mini", 0.8)


class FakeWarehouse:
    """First execute() is the schema lookup, later ones are the generated SQL."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, int | None]] = []

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        self.calls.append((sql, max_rows))
        if "INFORMATION_SCHEMA" in sql:
            return METADATA
        if "no_such_column" in sql:
            raise WarehouseError("SQL compilation error: invalid identifier 'NO_SUCH_COLUMN'")
        return self.rows[:max_rows] if max_rows else self.rows


def test_schema_context_lists_real_columns_with_their_meaning() -> None:
    assert format_schema_context(METADATA) == (
        "FINSIGHT.MART.MART_ASSET_DAILY: One row per asset per day.\n"
        "  SYMBOL TEXT: Binance pair.\n"
        "  CLOSE_PRICE NUMBER"
    )


def test_the_tables_in_the_metadata_are_the_allowlist() -> None:
    assert table_names(METADATA) == {ASSET}


def test_user_prompt_carries_today_so_last_month_can_be_resolved() -> None:
    prompt = build_user_prompt("Last month?", "SCHEMA TEXT", date(2026, 9, 28))

    assert prompt.startswith("Today (UTC): 2026-09-28")
    assert "SCHEMA TEXT" in prompt and prompt.endswith("Last month?")


def test_system_prompt_includes_rules_and_verified_examples() -> None:
    text = system_prompt()

    assert "never SELECT *" in text
    assert "FINSIGHT.MART.MART_MARKET_MACRO_DAILY" in text  # from the few-shot examples


def test_the_guards_rewrite_is_what_runs_and_what_is_shown() -> None:
    warehouse = FakeWarehouse([{"N": 1}])

    answer = answer_question("How many?", llm=FakeLLM("SELECT 1 AS n;"), warehouse=warehouse)

    assert answer.sql == "SELECT\n  1 AS n\nLIMIT 100"
    assert warehouse.calls[-1][0] == answer.sql
    assert answer.rows == [{"N": 1}]
    assert answer.usage.cost_usd == 0.0003


def test_rows_are_capped_and_the_cut_is_reported() -> None:
    warehouse = FakeWarehouse([{"N": i} for i in range(10)])

    answer = answer_question("All?", llm=FakeLLM("SELECT n"), warehouse=warehouse, max_rows=3)

    assert answer.sql.endswith("LIMIT 3")  # the cap is in the SQL, so Snowflake stops early
    assert len(answer.rows) == 3
    assert answer.truncated is True


def test_a_limit_chosen_by_the_model_is_not_a_cut() -> None:
    warehouse = FakeWarehouse([{"N": i} for i in range(3)])
    llm = FakeLLM(f"SELECT close_price FROM {ASSET} ORDER BY close_price DESC LIMIT 3")

    answer = answer_question("Top 3?", llm=llm, warehouse=warehouse, max_rows=3)

    assert len(answer.rows) == 3
    assert answer.truncated is False  # "top 3" asked for 3 rows; nothing was hidden


@pytest.mark.parametrize(
    ("sql", "violation"),
    [(f"DELETE FROM {ASSET}", "not_select"),
     ("SELECT symbol FROM FINSIGHT.RAW.RAW_BINANCE_KLINE", "table_not_allowed")],
)  # fmt: skip
def test_blocked_sql_never_reaches_snowflake(sql: str, violation: str) -> None:
    warehouse = FakeWarehouse([])

    answer = answer_question("Anything", llm=FakeLLM(sql), warehouse=warehouse)

    assert answer.error.startswith("Blocked by the SQL guard")
    assert answer.violations == (violation,)
    assert answer.sql == sql  # shown to the analyst, although it did not run
    assert all("INFORMATION_SCHEMA" in called for called, _ in warehouse.calls)


def test_failed_sql_is_returned_with_its_error_not_lost() -> None:
    llm = FakeLLM(f"SELECT no_such_column FROM {ASSET}")

    answer = answer_question("Oops?", llm=llm, warehouse=FakeWarehouse([]))

    assert "no_such_column" in answer.sql
    assert "invalid identifier" in answer.error
    assert answer.rows == []


def test_unanswerable_question_runs_no_sql() -> None:
    warehouse = FakeWarehouse([])

    answer = answer_question(
        "Stock price of Apple?", llm=FakeLLM("", "No stock data."), warehouse=warehouse
    )

    assert answer.sql == "" and answer.rows == []
    assert all("INFORMATION_SCHEMA" in sql for sql, _ in warehouse.calls)


def test_agent_settings_swap_in_the_read_only_user(tmp_path: Path) -> None:
    key = tmp_path / "agent.p8"
    settings = Settings(
        _env_file=None,
        snowflake_user="FINSIGHT_SVC",
        snowflake_agent_user="FINSIGHT_AGENT_SVC",
        snowflake_agent_private_key_path=key,
    )

    agent = settings.for_agent()

    assert (agent.snowflake_user, agent.snowflake_role) == ("FINSIGHT_AGENT_SVC", "FINSIGHT_AGENT")
    assert agent.snowflake_private_key_path == key
    assert settings.snowflake_user == "FINSIGHT_SVC"  # the original is untouched


def test_agent_settings_missing_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="SNOWFLAKE_AGENT_USER"):
        Settings(_env_file=None).for_agent()
