"""Unit tests for the SQL guard: which SQL may reach Snowflake, and how it is rewritten."""

import pytest
import sqlglot
from sqlglot import exp

from src.services.sql_guard import SQLGuard

ASSET = "FINSIGHT.MART.MART_ASSET_DAILY"
MACRO = "FINSIGHT.MART.MART_MACRO_DAILY"
GUARD = SQLGuard(allowed_tables={ASSET, MACRO}, max_rows=100)


def violations_of(sql: str) -> tuple[str, ...]:
    """Run the guard on SQL that must be blocked and return its violation codes."""

    result = GUARD.validate_and_rewrite(sql)
    assert not result.is_valid
    assert result.sql is None  # nothing to execute
    assert result.error  # a human-readable reason, for logs and the repair prompt
    return result.violations


# --- What passes, and how it is rewritten --------------------------------------------------


def test_a_plain_select_passes_and_gets_a_limit() -> None:
    result = GUARD.validate_and_rewrite(f"SELECT symbol, close_price FROM {ASSET}")

    assert result.is_valid and result.violations == ()
    assert result.sql.endswith("LIMIT 100")
    assert result.limit_enforced is True


def test_a_small_limit_written_by_the_model_is_kept() -> None:
    result = GUARD.validate_and_rewrite(
        f"SELECT trade_date FROM {ASSET} ORDER BY trade_date DESC LIMIT 7"
    )

    assert result.sql.endswith("LIMIT 7")
    assert result.limit_enforced is False


@pytest.mark.parametrize(
    "row_clause",
    ["LIMIT 5000", "LIMIT NULL", "FETCH FIRST 500 ROWS ONLY", "LIMIT 5 + 5"],
    ids=["too-big", "null-means-no-limit", "fetch", "not-a-plain-number"],
)
def test_a_limit_that_is_too_big_or_not_a_plain_number_is_replaced(row_clause: str) -> None:
    result = GUARD.validate_and_rewrite(f"SELECT symbol FROM {ASSET} {row_clause}")

    assert result.sql.endswith("LIMIT 100")
    assert result.limit_enforced is True


def test_top_is_a_limit_too() -> None:
    result = GUARD.validate_and_rewrite(f"SELECT TOP 1000 symbol FROM {ASSET}")

    assert "TOP" not in result.sql and result.sql.endswith("LIMIT 100")


def test_a_union_gets_one_limit_for_the_whole_result() -> None:
    result = GUARD.validate_and_rewrite(
        f"SELECT 'BTC' AS s, close_price FROM {ASSET} "
        f"UNION ALL SELECT 'ETH', close_price FROM {ASSET}"
    )

    assert result.is_valid
    assert result.sql.count("LIMIT") == 1 and result.sql.endswith("LIMIT 100")


def test_ctes_windows_joins_and_subqueries_are_allowed() -> None:
    sql = f"""
        WITH daily AS (
            SELECT a.trade_date, a.log_return, m.treasury_10y,
                   LAG(m.treasury_10y) OVER (ORDER BY a.trade_date) AS prev_10y
            FROM {ASSET} AS a
            JOIN {MACRO} AS m ON m.market_date = a.trade_date
            WHERE a.symbol = 'ETHUSDT'
        )
        SELECT STDDEV_SAMP(log_return) * SQRT(365) AS volatility
        FROM daily
        WHERE treasury_10y > prev_10y
          AND trade_date IN (SELECT market_date FROM {MACRO} WHERE treasury_10y > 4)
    """

    result = GUARD.validate_and_rewrite(sql)

    # "daily" is read like a table, but it is the CTE defined above: not a table to allowlist.
    assert result.is_valid, result.error


def test_table_names_are_compared_case_insensitively() -> None:
    result = GUARD.validate_and_rewrite("select close_price from finsight.mart.mart_asset_daily")

    assert result.is_valid


def test_the_rewrite_is_stable_and_passes_the_guard_again() -> None:
    first = GUARD.validate_and_rewrite(
        f"WITH x AS (SELECT symbol, close_price FROM {ASSET}) SELECT symbol FROM x -- note"
    )
    second = GUARD.validate_and_rewrite(first.sql)

    assert second.is_valid and second.sql == first.sql
    assert second.limit_enforced is False  # the LIMIT 100 we added is now simply kept


# --- What is blocked -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        f"DELETE FROM {ASSET}",
        f"DROP TABLE {ASSET}",
        f"UPDATE {ASSET} SET close_price = 0",
        f"INSERT INTO {ASSET} (symbol) VALUES ('X')",
        f"TRUNCATE TABLE {ASSET}",
        f"ALTER TABLE {ASSET} RENAME TO old_asset",
        "CREATE TABLE FINSIGHT.MART.COPY_OF_ASSET AS SELECT 1 AS x",
        f"MERGE INTO {ASSET} t USING {MACRO} s ON t.trade_date = s.market_date "
        "WHEN MATCHED THEN DELETE",
        "GRANT ROLE ACCOUNTADMIN TO USER FINSIGHT_AGENT_SVC",
        "USE ROLE FINSIGHT_ENGINEER",
        "CALL FINSIGHT.MART.SOME_PROCEDURE()",
        "SHOW TABLES",
    ],
    ids=["delete", "drop", "update", "insert", "truncate", "alter", "create", "merge", "grant",
         "use-role", "call", "show"],  # fmt: skip
)
def test_anything_but_a_select_is_blocked(sql: str) -> None:
    assert "not_select" in violations_of(sql)


@pytest.mark.parametrize(
    "sql",
    [
        f"WITH gone AS (DELETE FROM {ASSET} RETURNING symbol) SELECT symbol FROM gone",
        f"SELECT symbol INTO FINSIGHT.MART.STOLEN FROM {ASSET}",
    ],
    ids=["delete-inside-cte", "select-into"],
)
def test_a_write_hidden_inside_a_select_is_blocked(sql: str) -> None:
    assert "forbidden_statement" in violations_of(sql)


def test_a_second_statement_is_blocked() -> None:
    assert violations_of(f"SELECT 1 AS x; DROP TABLE {ASSET}") == ("multiple_statements",)


def test_dangerous_words_inside_text_are_just_text() -> None:
    # A regex looking for "DROP" would block this. The syntax tree knows it is a string value.
    result = GUARD.validate_and_rewrite("SELECT 'DROP TABLE x; --' AS note")

    assert result.is_valid


def test_a_comment_cannot_smuggle_a_second_statement_into_the_rewrite() -> None:
    # sqlglot reads this as ONE select with a comment. Printing the comment back as /* */ would
    # turn "*/" into the end of that comment and "; DROP TABLE t" into a real second statement.
    result = GUARD.validate_and_rewrite("SELECT 1 AS x -- */ ; DROP TABLE t")

    assert result.is_valid
    assert "DROP" not in result.sql
    assert len(sqlglot.parse(result.sql, read="snowflake")) == 1


@pytest.mark.parametrize(
    "table",
    [
        "FINSIGHT.RAW.RAW_BINANCE_KLINE",
        "FINSIGHT.CORE.FCT_CRYPTO_KLINE_1H",
        "FINSIGHT.INFORMATION_SCHEMA.TABLES",
        "SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY",
    ],
)
def test_tables_outside_the_allowlist_are_blocked(table: str) -> None:
    assert violations_of(f"SELECT symbol FROM {table}") == ("table_not_allowed",)


@pytest.mark.parametrize(
    "source",
    ["mart_asset_daily", "MART.MART_ASSET_DAILY", "IDENTIFIER('FINSIGHT.RAW.RAW_BINANCE_KLINE')"],
    ids=["bare-name", "schema-and-name", "identifier-function"],
)
def test_tables_must_be_written_in_full(source: str) -> None:
    # A short name depends on the session's current database/schema; IDENTIFIER() hides the name
    # inside a string. Either way the guard cannot tell which table would really be read.
    assert violations_of(f"SELECT symbol FROM {source}") == ("unqualified_table",)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT query_text FROM TABLE(FINSIGHT.INFORMATION_SCHEMA.QUERY_HISTORY())",
        f"SELECT f.value FROM {ASSET} AS a, LATERAL FLATTEN(input => a.symbol) AS f",
    ],
    ids=["table-function", "lateral-flatten"],
)
def test_table_functions_cannot_go_around_the_allowlist(sql: str) -> None:
    assert "table_function" in violations_of(sql)


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT * FROM {ASSET}",
        f"SELECT a.* FROM {ASSET} AS a",
        f"WITH x AS (SELECT * FROM {ASSET}) SELECT symbol FROM x",
    ],
    ids=["star", "table-star", "star-inside-cte"],
)
def test_select_star_is_blocked(sql: str) -> None:
    assert violations_of(sql) == ("select_star",)


def test_count_star_is_not_select_star() -> None:
    assert GUARD.validate_and_rewrite(f"SELECT COUNT(*) AS days FROM {ASSET}").is_valid


def test_system_functions_are_blocked() -> None:
    assert violations_of("SELECT SYSTEM$CANCEL_ALL_QUERIES(1) AS x") == ("forbidden_function",)


@pytest.mark.parametrize(
    ("sql", "code"),
    [("", "empty"), ("  ;  ", "empty"), ("SELEC symbol FROM", "parse_error")],
)
def test_empty_or_broken_sql_is_rejected(sql: str, code: str) -> None:
    assert violations_of(sql) == (code,)


def test_every_violation_is_reported_at_once() -> None:
    # The repair loop can then fix everything in one retry instead of one per retry.
    result = GUARD.validate_and_rewrite("SELECT * FROM FINSIGHT.RAW.RAW_BINANCE_KLINE")

    assert set(result.violations) == {"select_star", "table_not_allowed"}
    assert "SELECT *" in result.error and "FINSIGHT.RAW.RAW_BINANCE_KLINE" in result.error


def test_an_empty_allowlist_blocks_every_table() -> None:
    # Fail closed: if the metadata lookup returned nothing, nothing can be read.
    result = SQLGuard(allowed_tables=set()).validate_and_rewrite(f"SELECT symbol FROM {ASSET}")

    assert result.violations == ("table_not_allowed",)


def test_a_rewrite_that_does_not_parse_back_to_one_query_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate a bug in sqlglot's SQL printer: our own output is input to Snowflake too.
    monkeypatch.setattr(exp.Select, "sql", lambda self, **kwargs: "SELECT 1; DROP TABLE t")

    assert violations_of(f"SELECT symbol FROM {ASSET}") == ("rewrite_failed",)
