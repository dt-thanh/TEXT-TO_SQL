"""Unit tests for the LangGraph workflow and its repair loop, with a scripted LLM and fakes.

No token is spent: ScriptedLLM plays back answers in order, FakeWarehouse fails on chosen SQL.
"""

from typing import Any

import pytest

from src.agents.graph import build_graph
from src.agents.text_to_sql import answer_question
from src.common.exceptions import WarehouseError
from src.services.llm import LLMResult, LLMUsage

ASSET = "FINSIGHT.MART.MART_ASSET_DAILY"
METADATA = [
    {"TABLE_NAME": "MART_ASSET_DAILY", "TABLE_COMMENT": "One row per asset per day.",
     "COLUMN_NAME": "CLOSE_PRICE", "DATA_TYPE": "NUMBER", "COLUMN_COMMENT": ""},
]  # fmt: skip
GOOD_SQL = f"SELECT close_price FROM {ASSET}"
BAD_COLUMN_SQL = f"SELECT no_such_column FROM {ASSET}"
COMPILATION_ERROR = (
    "Query failed: 000904 (42000): SQL compilation error: invalid identifier 'NO_SUCH_COLUMN'"
)


class ScriptedLLM:
    """Returns the scripted SQL answers one per call; the last one repeats."""

    def __init__(self, *sqls: str) -> None:
        self.sqls = list(sqls)
        self.prompts: list[str] = []

    def generate_json(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResult:
        self.prompts.append(user_prompt)
        sql = self.sqls[min(len(self.prompts), len(self.sqls)) - 1]
        usage = LLMUsage(input_tokens=1000, output_tokens=100, cost_usd=0.0002)
        return LLMResult({"sql": sql, "explanation": "1. Step."}, usage, "gpt-4o-mini", 0.5)


class FakeWarehouse:
    def __init__(self, error: str = COMPILATION_ERROR) -> None:
        self.error = error
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        if "INFORMATION_SCHEMA" in sql:
            return METADATA
        self.queries.append(sql)
        if "no_such_column" in sql:
            raise WarehouseError(self.error)
        return [{"CLOSE_PRICE": 1}]


def ask(llm: ScriptedLLM, warehouse: FakeWarehouse | None = None, **kwargs: Any) -> Any:
    return answer_question("Close?", llm=llm, warehouse=warehouse or FakeWarehouse(), **kwargs)


def test_a_correct_first_attempt_needs_one_llm_call_and_no_repair() -> None:
    llm = ScriptedLLM(GOOD_SQL)

    answer = ask(llm)

    assert answer.rows == [{"CLOSE_PRICE": 1}] and answer.error is None
    assert len(llm.prompts) == 1 and answer.repairs == 0 and answer.attempts == ()
    assert answer.seconds > 0  # the whole question is timed, not only the LLM and SQL parts


def test_every_question_leaves_one_summary_line_in_the_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # One line per question with status, repairs, cost and time is enough to follow cost and
    # quality in production from the logs alone.
    caplog.set_level("INFO", logger="src.agents.text_to_sql")

    ask(ScriptedLLM(BAD_COLUMN_SQL, GOOD_SQL))

    summaries = [r.getMessage() for r in caplog.records if r.getMessage().startswith("question ")]
    assert len(summaries) == 1
    assert "status=answered" in summaries[0] and "repairs=1" in summaries[0]
    assert "cost_usd=0.00040" in summaries[0]


def test_a_snowflake_compilation_error_is_sent_back_and_repaired() -> None:
    llm = ScriptedLLM(BAD_COLUMN_SQL, GOOD_SQL)

    answer = ask(llm)

    assert answer.rows == [{"CLOSE_PRICE": 1}] and answer.error is None
    assert answer.repairs == 1
    repair_prompt = llm.prompts[1]
    assert "no_such_column" in repair_prompt  # the failed SQL ...
    assert "invalid identifier 'NO_SUCH_COLUMN'" in repair_prompt  # ... and why it failed
    assert repair_prompt.startswith(llm.prompts[0])  # the original question message comes first
    assert answer.attempts[0]["error"] == COMPILATION_ERROR  # kept for the analyst to see


def test_a_guard_violation_is_repaired_without_reaching_snowflake() -> None:
    llm = ScriptedLLM(f"SELECT * FROM {ASSET}", GOOD_SQL)
    warehouse = FakeWarehouse()

    answer = ask(llm, warehouse)

    assert answer.repairs == 1 and answer.rows
    assert len(warehouse.queries) == 1  # only the repaired SQL ran
    assert "SELECT * is not allowed" in llm.prompts[1]


@pytest.mark.parametrize(
    "sql",
    [f"DELETE FROM {ASSET}", f"SELECT 1 AS x; DROP TABLE {ASSET}"],
    ids=["write", "second-statement"],
)
def test_an_attempt_to_write_is_never_repaired(sql: str) -> None:
    # Asking the model to "fix" a DELETE would only teach it to get around the guard.
    llm = ScriptedLLM(sql, GOOD_SQL)

    answer = ask(llm)

    assert len(llm.prompts) == 1 and answer.repairs == 0
    assert answer.error.startswith("Blocked by the SQL guard") and answer.rows == []


def test_an_error_a_rewrite_cannot_fix_is_not_repaired() -> None:
    timeout = "Query failed: 000630 (57014): Statement reached its statement or warehouse timeout"
    llm = ScriptedLLM(BAD_COLUMN_SQL, GOOD_SQL)

    answer = ask(llm, FakeWarehouse(error=timeout))

    assert len(llm.prompts) == 1 and answer.error == timeout


def test_repairs_stop_at_the_limit_and_keep_every_failed_attempt() -> None:
    llm = ScriptedLLM(BAD_COLUMN_SQL)  # never learns

    answer = ask(llm, max_repairs=2)

    assert len(llm.prompts) == 3  # 1 attempt + 2 repairs, then stop
    assert answer.repairs == 2 and len(answer.attempts) == 3
    assert "invalid identifier" in answer.error and answer.rows == []
    assert "## Attempt 2" in llm.prompts[2]  # the last repair sees both earlier failures


def test_cost_and_time_add_up_over_every_call() -> None:
    answer = ask(ScriptedLLM(BAD_COLUMN_SQL), max_repairs=2)

    assert answer.usage.input_tokens == 3000 and answer.usage.output_tokens == 300
    assert answer.usage.cost_usd == pytest.approx(0.0006)
    assert answer.llm_seconds == pytest.approx(1.5)


def test_the_model_may_give_up_during_a_repair() -> None:
    llm = ScriptedLLM(BAD_COLUMN_SQL, "")

    answer = ask(llm)

    assert answer.sql == "" and answer.error is None  # a clean "cannot answer", nothing stale
    assert answer.repairs == 1 and len(answer.attempts) == 1


def test_no_repairs_allowed_is_the_old_single_attempt_behaviour() -> None:
    llm = ScriptedLLM(BAD_COLUMN_SQL, GOOD_SQL)

    answer = ask(llm, max_repairs=0)

    assert len(llm.prompts) == 1 and "invalid identifier" in answer.error


def test_the_graph_has_the_nodes_of_spec_section_20() -> None:
    graph = build_graph(llm=None, warehouse=None, max_rows=100)

    nodes = set(graph.get_graph().nodes) - {"__start__", "__end__"}

    expected = {"retrieve_context", "generate_sql", "validate_sql", "execute_sql", "repair_sql"}
    assert nodes == expected


def test_a_result_with_duplicate_column_names_is_sent_back_for_aliases() -> None:
    duplicate = "Query returned duplicate column names: AVG(CLOSE_PRICE). Give every column..."
    llm = ScriptedLLM(BAD_COLUMN_SQL, GOOD_SQL)

    answer = ask(llm, FakeWarehouse(error=duplicate))

    assert answer.repairs == 1 and answer.rows and answer.error is None
