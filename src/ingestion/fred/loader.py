"""Load FRED series metadata and observation vintages into RAW, idempotently.

Only the table descriptions live here; the MERGE mechanics are in src/ingestion/merge_loader.py.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from src.ingestion.fred.extractor import FredObservation, FredSeries
from src.ingestion.merge_loader import LoadResult, TableSpec, merge_rows

SERIES_TABLE = "FINSIGHT.RAW.RAW_FRED_SERIES"
OBSERVATION_TABLE = "FINSIGHT.RAW.RAW_FRED_OBSERVATION"

SERIES_SPEC = TableSpec(
    target_table=SERIES_TABLE,
    stage_table="FINSIGHT.RAW.TMP_FRED_SERIES_LOAD",
    key_columns=("series_id",),
    value_columns=(
        "title",
        "frequency",
        "frequency_short",
        "units",
        "seasonal_adjustment",
        "observation_start",
        "observation_end",
        "source_last_updated",
    ),
    metadata_columns=("ingested_at",),
    dedupe_order_by="source_last_updated DESC",
)

# Grain: one series + one observation date + one vintage. A revision is a NEW row with a later
# realtime_start, never an update of the old one: the old value must stay to avoid look-ahead bias.
OBSERVATION_SPEC = TableSpec(
    target_table=OBSERVATION_TABLE,
    stage_table="FINSIGHT.RAW.TMP_FRED_OBSERVATION_LOAD",
    key_columns=("series_id", "observation_date", "realtime_start"),
    value_columns=("value_raw", "value"),
    metadata_columns=("ingested_at", "batch_id"),
    dedupe_order_by="value_raw",
)


def series_row(series: FredSeries, ingested_at: datetime) -> tuple[Any, ...]:
    columns = SERIES_SPEC.key_columns + SERIES_SPEC.value_columns
    return (*(getattr(series, c) for c in columns), ingested_at)


def observation_row(obs: FredObservation, batch_id: str, ingested_at: datetime) -> tuple[Any, ...]:
    columns = OBSERVATION_SPEC.key_columns + OBSERVATION_SPEC.value_columns
    return (*(getattr(obs, c) for c in columns), ingested_at, batch_id)


def load_series(conn: Any, series: FredSeries, batch_id: str) -> LoadResult:
    rows = [series_row(series, datetime.now(UTC))]
    return merge_rows(conn, SERIES_SPEC, rows, batch_id)


def load_observations(
    conn: Any,
    observations: Sequence[FredObservation],
    batch_id: str,
    ingested_at: datetime | None = None,
    target_table: str = OBSERVATION_TABLE,
) -> LoadResult:
    ingested_at = ingested_at or datetime.now(UTC)
    rows = [observation_row(obs, batch_id, ingested_at) for obs in observations]
    return merge_rows(conn, OBSERVATION_SPEC, rows, batch_id, target_table)
