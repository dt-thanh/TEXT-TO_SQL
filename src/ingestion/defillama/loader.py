"""Load DefiLlama TVL into RAW.RAW_DEFILLAMA_CHAIN_TVL, keeping its own revision history.

DefiLlama publishes no vintages and may recompute past TVL. Each run therefore stores a value only
when it is new or differs from the newest value already stored for that (chain, day). The fetch
day is part of the grain, so the table becomes a vintage history, like realtime_start for FRED:
"what did DefiLlama say on day X" stays answerable for every day the pipeline has run.

Grain: chain + tvl_date + fetched_date. Re-running on the same day changes nothing.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from src.ingestion.defillama.extractor import ChainTvl
from src.ingestion.merge_loader import LoadResult, TableSpec, merge_rows

RAW_TABLE = "FINSIGHT.RAW.RAW_DEFILLAMA_CHAIN_TVL"
STAGE_TABLE = "FINSIGHT.RAW.TMP_DEFILLAMA_CHAIN_TVL_LOAD"
# A relative change smaller than this is rounding noise, not a revision.
REVISION_TOLERANCE = 1e-6

TVL_SPEC = TableSpec(
    target_table=RAW_TABLE,
    stage_table=STAGE_TABLE,
    key_columns=("chain", "tvl_date", "fetched_date"),
    value_columns=("tvl_usd", "is_backfill"),
    metadata_columns=("ingested_at", "batch_id"),
    dedupe_order_by="tvl_usd",
)


def build_versioned_merge_sql(target_table: str, stage_table: str = STAGE_TABLE) -> str:
    """Keep staged values that are new or revised compared with what earlier fetches stored.

    "Earlier" excludes today's fetch, so a second run on the same day matches today's rows and
    changes nothing (or corrects them if DefiLlama moved again in between).
    """

    columns = ", ".join(TVL_SPEC.columns)
    staged = ", ".join(f"stage.{c}" for c in TVL_SPEC.columns)
    source_values = ", ".join(f"source.{c}" for c in TVL_SPEC.columns)
    return f"""
MERGE INTO {target_table} AS target
USING (
    SELECT {staged}
    FROM {stage_table} AS stage
    LEFT JOIN (
        SELECT chain, tvl_date, tvl_usd
        FROM {target_table}
        WHERE fetched_date < (SELECT MAX(fetched_date) FROM {stage_table})
        QUALIFY ROW_NUMBER() OVER (PARTITION BY chain, tvl_date ORDER BY fetched_date DESC) = 1
    ) AS known
        ON known.chain = stage.chain AND known.tvl_date = stage.tvl_date
    WHERE known.tvl_usd IS NULL
       OR ABS(stage.tvl_usd - known.tvl_usd) > {REVISION_TOLERANCE} * ABS(known.tvl_usd)
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY stage.chain, stage.tvl_date, stage.fetched_date ORDER BY stage.tvl_usd
    ) = 1
) AS source
ON target.chain = source.chain
   AND target.tvl_date = source.tvl_date
   AND target.fetched_date = source.fetched_date
WHEN MATCHED AND target.tvl_usd IS DISTINCT FROM source.tvl_usd THEN UPDATE SET
    tvl_usd = source.tvl_usd, ingested_at = source.ingested_at, batch_id = source.batch_id
WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({source_values})
"""


def to_row(
    point: ChainTvl, fetched_date: date, is_backfill: bool, batch_id: str, ingested_at: datetime
) -> tuple[Any, ...]:
    """One stage-table row, in TVL_SPEC.columns order."""

    return (
        point.chain,
        point.tvl_date,
        fetched_date,
        point.tvl_usd,
        is_backfill,
        ingested_at,
        batch_id,
    )


def load_chain_tvl(
    conn: Any,
    points: Sequence[ChainTvl],
    fetched_date: date,
    is_backfill: bool,
    batch_id: str,
    ingested_at: datetime | None = None,
    target_table: str = RAW_TABLE,
) -> LoadResult:
    """Store the new and revised TVL values of one fetch."""

    ingested_at = ingested_at or datetime.now(UTC)
    rows = [to_row(p, fetched_date, is_backfill, batch_id, ingested_at) for p in points]
    merge_sql = build_versioned_merge_sql(target_table)
    return merge_rows(conn, TVL_SPEC, rows, batch_id, target_table, merge_sql=merge_sql)
