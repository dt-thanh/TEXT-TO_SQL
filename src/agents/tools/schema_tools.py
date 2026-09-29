"""Describe the MART tables to the language model, straight from Snowflake's metadata.

Table and column names come from INFORMATION_SCHEMA, so the model is only ever shown columns
that really exist (spec rule 6: never invent names). The descriptions are the ones written in
dbt/models/marts/_marts.yml, which dbt copies into Snowflake as COMMENTs (persist_docs).

The same rows give the SQL guard its table allowlist: the tables the model is shown are exactly
the tables its SQL may read.
"""

import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any
from weakref import WeakKeyDictionary

SCHEMA = "MART"
# The MART schema changes when dbt changes a model, at most once a day; reading it costs a query.
# A new column reaches the agent at most this late.
SCHEMA_TTL_SECONDS = 600

SCHEMA_SQL = """
select
    t.table_name,
    t.comment      as table_comment,
    c.column_name,
    c.data_type,
    c.comment      as column_comment,
    -- How recent the data is, in the same round trip: the newest finished day in the marts.
    (select max(trade_date) from FINSIGHT.MART.MART_ASSET_DAILY) as latest_trade_date
from FINSIGHT.INFORMATION_SCHEMA.TABLES as t
join FINSIGHT.INFORMATION_SCHEMA.COLUMNS as c
    on  c.table_schema = t.table_schema
    and c.table_name   = t.table_name
where t.table_schema = %(schema)s
order by t.table_name, c.ordinal_position
"""


@dataclass(frozen=True)
class SchemaContext:
    """One metadata read, two uses: the text the model sees and the tables the guard allows."""

    prompt_text: str
    tables: frozenset[str]  # fully qualified, e.g. FINSIGHT.MART.MART_ASSET_DAILY
    data_as_of: date | None = None  # newest finished UTC day in the marts


def format_schema_context(rows: list[dict[str, Any]], database: str = "FINSIGHT") -> str:
    """Turn metadata rows into a compact text block: one line per table, one per column."""

    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tables[row["TABLE_NAME"]].append(row)

    lines = []
    for table_name, columns in tables.items():
        table_comment = (columns[0]["TABLE_COMMENT"] or "").strip()
        lines.append(f"{database}.{SCHEMA}.{table_name}: {table_comment}".rstrip(": "))
        for column in columns:
            comment = (column["COLUMN_COMMENT"] or "").strip()
            line = f"  {column['COLUMN_NAME']} {column['DATA_TYPE']}"
            lines.append(f"{line}: {comment}" if comment else line)
        lines.append("")
    return "\n".join(lines).strip()


def table_names(rows: list[dict[str, Any]], database: str = "FINSIGHT") -> frozenset[str]:
    return frozenset(f"{database}.{SCHEMA}.{row['TABLE_NAME']}" for row in rows)


# One cached context per warehouse client, forgotten when the client is garbage-collected.
_cache: "WeakKeyDictionary[Any, tuple[float, SchemaContext]]" = WeakKeyDictionary()


def get_schema_context(client: Any, clock: Callable[[], float] = time.monotonic) -> SchemaContext:
    """Prompt text and table allowlist. `client` is a SnowflakeClient (the agent's, in production).

    Read from Snowflake at most once per SCHEMA_TTL_SECONDS per client. If the lookup returns no
    rows, the allowlist is empty and the guard blocks every table.
    """

    cached = _cache.get(client)
    if cached and clock() - cached[0] < SCHEMA_TTL_SECONDS:
        return cached[1]
    rows = client.execute(SCHEMA_SQL, {"schema": SCHEMA})
    context = SchemaContext(
        prompt_text=format_schema_context(rows),
        tables=table_names(rows),
        data_as_of=rows[0].get("LATEST_TRADE_DATE") if rows else None,
    )
    _cache[client] = (clock(), context)
    return context
