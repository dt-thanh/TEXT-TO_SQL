"""Define sqlglot-backed safety checks and query rewriting.

TODO: Block DML/DDL and SELECT *, permit approved SELECTs, and enforce LIMIT.
"""

from dataclasses import dataclass

import sqlglot


@dataclass(frozen=True)
class SQLValidationResult:
    """Structured outcome returned by the future SQL policy engine.

    TODO: Add machine-readable violation codes for repair prompts and metrics.
    """

    is_valid: bool
    sql: str | None = None
    error: str | None = None


class SQLGuard:
    """Declare SQL validation and LIMIT-rewriting behavior.

    TODO: Traverse the sqlglot AST and implement an explicit allowlist policy.
    """

    def __init__(self, max_rows: int = 500) -> None:
        self.max_rows = max_rows

    def validate_and_rewrite(self, sql: str) -> SQLValidationResult:
        """Validate Snowflake SQL and return a safe rewritten statement.

        TODO: Parse with dialect='snowflake', reject writes/stars, and add LIMIT.
        """

        _ = (sql, sqlglot)
        raise NotImplementedError("TODO: implement sqlglot safety validation")
