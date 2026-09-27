"""Upsert rows into a RAW table via a temporary stage table and one MERGE. Shared by all sources.

A source describes its table once with a TableSpec (which columns form the grain, which hold
values, which are load metadata); this module does the rest:
rows → temporary stage table (this session only) → MERGE on the grain → commit.
Re-loading the same rows changes nothing; a changed row updates in place.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.exceptions import WarehouseError

logger = logging.getLogger(__name__)

INSERT_BATCH_ROWS = 2000


@dataclass(frozen=True)
class TableSpec:
    """How one RAW table is loaded."""

    target_table: str
    stage_table: str
    key_columns: tuple[str, ...]
    value_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...]
    # Tie-break when a batch contains the same key twice (it should not, but MERGE would fail).
    dedupe_order_by: str

    @property
    def columns(self) -> tuple[str, ...]:
        return self.key_columns + self.value_columns + self.metadata_columns


@dataclass(frozen=True)
class LoadResult:
    """What one load did to the target table."""

    batch_id: str
    rows_received: int
    rows_inserted: int
    rows_updated: int


def new_batch_id() -> str:
    """Readable, unique id for one load, e.g. 20260927T101500Z-1a2b3c4d."""

    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"


def build_merge_sql(spec: TableSpec, target_table: str) -> str:
    """MERGE the stage table into `target_table` on the grain; unchanged rows are left alone."""

    columns = ", ".join(spec.columns)
    key_match = " AND ".join(f"target.{c} = source.{c}" for c in spec.key_columns)
    changed = " OR ".join(f"target.{c} IS DISTINCT FROM source.{c}" for c in spec.value_columns)
    updates = ", ".join(f"{c} = source.{c}" for c in spec.value_columns + spec.metadata_columns)
    source_values = ", ".join(f"source.{c}" for c in spec.columns)
    return f"""
MERGE INTO {target_table} AS target
USING (
    SELECT {columns}
    FROM {spec.stage_table}
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY {", ".join(spec.key_columns)} ORDER BY {spec.dedupe_order_by}
    ) = 1
) AS source
ON {key_match}
WHEN MATCHED AND ({changed}) THEN UPDATE SET {updates}
WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({source_values})
"""


def merge_rows(
    conn: Any,
    spec: TableSpec,
    rows: Sequence[tuple[Any, ...]],
    batch_id: str,
    target_table: str | None = None,
    batch_rows: int = INSERT_BATCH_ROWS,
) -> LoadResult:
    """Upsert `rows` (tuples in spec.columns order) into the target table.

    If anything fails before the MERGE, the target is untouched: the stage table is
    TEMPORARY and disappears with the session.
    """

    target = target_table or spec.target_table
    if not rows:
        return LoadResult(batch_id, 0, 0, 0)

    placeholders = ", ".join(["%s"] * len(spec.columns))
    insert_sql = (
        f"INSERT INTO {spec.stage_table} ({', '.join(spec.columns)}) VALUES ({placeholders})"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE OR REPLACE TEMPORARY TABLE {spec.stage_table} LIKE {target}")
            for start in range(0, len(rows), batch_rows):
                cur.executemany(insert_sql, list(rows[start : start + batch_rows]))
            cur.execute(build_merge_sql(spec, target))
            inserted, updated = cur.fetchone()
    except SnowflakeDriverError as err:
        raise WarehouseError(f"Loading batch {batch_id} into {target} failed: {err}") from err

    result = LoadResult(batch_id, len(rows), inserted, updated)
    logger.debug(
        "Loaded batch %s into %s: %d received, %d inserted, %d updated",
        batch_id,
        target,
        result.rows_received,
        result.rows_inserted,
        result.rows_updated,
    )
    return result
