"""Describe the MART tables to the language model, straight from Snowflake's metadata.

Table and column names come from INFORMATION_SCHEMA, so the model is only ever shown columns
that really exist (spec rule 6: never invent names). The descriptions are the ones written in
dbt/models/marts/_marts.yml, which dbt copies into Snowflake as COMMENTs (persist_docs).
"""

from collections import defaultdict
from typing import Any

SCHEMA = "MART"

SCHEMA_SQL = """
select
    t.table_name,
    t.comment      as table_comment,
    c.column_name,
    c.data_type,
    c.comment      as column_comment
from FINSIGHT.INFORMATION_SCHEMA.TABLES as t
join FINSIGHT.INFORMATION_SCHEMA.COLUMNS as c
    on  c.table_schema = t.table_schema
    and c.table_name   = t.table_name
where t.table_schema = %(schema)s
order by t.table_name, c.ordinal_position
"""


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


def get_schema_context(client: Any) -> str:
    """Schema text for the prompt. `client` is a SnowflakeClient (the agent's, in production)."""

    return format_schema_context(client.execute(SCHEMA_SQL, {"schema": SCHEMA}))
