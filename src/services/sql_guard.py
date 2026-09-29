"""Check generated SQL before it reaches Snowflake, and cap how many rows it can return (spec §23).

The model's SQL is untrusted input. The guard does not search the text for bad words; it parses
the SQL into a syntax tree with sqlglot and checks what each part of the tree IS:
- exactly one statement, and it is a query (SELECT, WITH ... SELECT, UNION of SELECTs);
- no write, DDL, permission or session statement anywhere in the tree, no SYSTEM$ function;
- every table is written in full (DATABASE.SCHEMA.TABLE) and is on the allowlist;
- rows come only from tables, CTEs and subqueries (no table functions around the allowlist);
- no SELECT *;
- a LIMIT no higher than max_rows (added or lowered when needed).

The SQL that runs is printed back from the checked tree, never the model's original text.
The guard is one layer of several: the query then runs as the read-only FINSIGHT_AGENT role with
a statement timeout, so a gap in these rules still cannot write or read outside MART.
"""

from collections.abc import Iterable
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

DIALECT = "snowflake"

# Statements that write data, change objects, permissions or the session. Checked in the whole
# tree, not only at the top: sqlglot also parses a DELETE hidden inside a CTE, or SELECT ... INTO.
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Copy,
    exp.Grant,
    exp.Use,
    exp.Command,
    exp.Into,
)

# One problem found in the SQL: (machine-readable code, human-readable message).
Violation = tuple[str, str]


@dataclass(frozen=True)
class SQLValidationResult:
    """What the guard decided. `sql` is set only when the query may run."""

    is_valid: bool
    sql: str | None = None
    error: str | None = None
    # Stable codes such as "select_star", for tests, metrics and the repair loop.
    violations: tuple[str, ...] = ()
    # True when the guard added or lowered the LIMIT: the row cap came from us, not the model.
    limit_enforced: bool = False


def blocked(*violations: Violation) -> SQLValidationResult:
    return SQLValidationResult(
        is_valid=False,
        error="; ".join(message for _, message in violations),
        violations=tuple(code for code, _ in violations),
    )


def select_violations(select: exp.Select) -> list[Violation]:
    """Rules for one SELECT: named columns only, rows only from tables and subqueries."""

    found = []
    if any(projection.is_star for projection in select.expressions):  # *, t.* (not COUNT(*))
        found.append(("select_star", "SELECT * is not allowed: name the columns"))

    sources = [select.args["from"].this] if select.args.get("from") else []
    sources += [join.this for join in select.args.get("joins") or []]
    for source in sources:
        # TABLE(...), LATERAL FLATTEN(...), VALUES ... have no table name to check.
        if not isinstance(source, exp.Table | exp.Subquery):
            text = source.sql(dialect=DIALECT)[:80]
            found.append(("table_function", f"{text}: read only from tables, CTEs or subqueries"))
    return found


class SQLGuard:
    """Validate one generated SQL statement and rewrite it into the SQL that will run."""

    def __init__(self, allowed_tables: Iterable[str], max_rows: int = 100) -> None:
        # Fully qualified names such as FINSIGHT.MART.MART_ASSET_DAILY. They come from our code
        # and Snowflake's metadata, never from the model: the LLM does not decide what it may read.
        self.allowed_tables = frozenset(name.upper() for name in allowed_tables)
        self.max_rows = max_rows

    def validate_and_rewrite(self, sql: str) -> SQLValidationResult:
        try:
            statements = [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]
        except SqlglotError as err:
            return blocked(("parse_error", f"the SQL does not parse: {err}"))
        if not statements:
            return blocked(("empty", "there is no SQL statement"))
        if len(statements) > 1:
            count = len(statements)
            return blocked(("multiple_statements", f"{count} statements: only one is allowed"))
        query = statements[0]
        if not isinstance(query, exp.Query):
            return blocked(("not_select", f"only a SELECT query may run, got {query.key.upper()}"))

        violations = self.policy_violations(query)
        if violations:
            return blocked(*violations)

        query, limit_enforced = self.cap_rows(query)
        # Print the checked tree without comments: a comment printed back as /* ... */ could end
        # early and turn its text into SQL. Then read our own output again, since it is what
        # Snowflake will receive.
        safe_sql = query.sql(dialect=DIALECT, pretty=True, comments=False)
        reparsed = [s for s in sqlglot.parse(safe_sql, read=DIALECT) if s is not None]
        if len(reparsed) != 1 or not isinstance(reparsed[0], exp.Query):
            return blocked(("rewrite_failed", "the rewritten SQL is not a single query"))
        return SQLValidationResult(is_valid=True, sql=safe_sql, limit_enforced=limit_enforced)

    def policy_violations(self, query: exp.Query) -> list[Violation]:
        """Every rule broken anywhere in the tree, so the repair loop can fix them all at once."""

        cte_names = {cte.alias_or_name.upper() for cte in query.find_all(exp.CTE)}
        found: list[Violation] = []
        for node in query.walk():
            if isinstance(node, FORBIDDEN_NODES):
                found.append(("forbidden_statement", f"{node.key.upper()} is not allowed"))
            elif isinstance(node, exp.Anonymous) and node.name.upper().startswith("SYSTEM$"):
                found.append(("forbidden_function", f"{node.name} is not allowed"))
            elif isinstance(node, exp.Table):
                found.extend(self.table_violations(node, cte_names))
            elif isinstance(node, exp.Select):
                found.extend(select_violations(node))
        return list(dict.fromkeys(found))  # drop exact repeats, keep the order

    def table_violations(self, table: exp.Table, cte_names: set[str]) -> list[Violation]:
        name = table.name.upper()
        if not table.db and name in cte_names:
            return []  # a CTE defined in this query, not a stored table
        if not (table.catalog and table.db and name):
            text = table.sql(dialect=DIALECT)
            return [("unqualified_table", f"{text}: write tables as DATABASE.SCHEMA.TABLE")]
        full_name = f"{table.catalog}.{table.db}.{name}".upper()
        if full_name not in self.allowed_tables:
            return [("table_not_allowed", f"{full_name} is not an allowed table")]
        return []

    def cap_rows(self, query: exp.Query) -> tuple[exp.Query, bool]:
        """The query with a LIMIT of at most max_rows, and whether the guard had to change it."""

        limit = query.args.get("limit")  # LIMIT n, TOP n and FETCH FIRST n ROWS all land here
        if limit is not None:
            count = limit.expression if isinstance(limit, exp.Limit) else limit.args.get("count")
            if isinstance(count, exp.Literal) and count.is_int and int(count.name) <= self.max_rows:
                return query, False
        # Replaces any other LIMIT: too big, LIMIT NULL (= no limit in Snowflake), an expression.
        return query.limit(self.max_rows), True
