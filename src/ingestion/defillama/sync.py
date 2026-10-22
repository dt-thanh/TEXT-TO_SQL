"""Keep RAW DefiLlama TVL current: one request per chain per run, the whole series each time.

There is no watermark: the series is small (a few thousand days) and fetching all of it is how
revisions of past days are noticed. The loader keeps only new or changed values.

The first load of a chain is a backfill: every value was fetched long after the day it describes,
so it is marked is_backfill and must not be presented as "known at the time".
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from snowflake.connector.errors import Error as SnowflakeDriverError

from src.common.exceptions import WarehouseError
from src.ingestion.defillama.client import ALL_CHAINS
from src.ingestion.defillama.extractor import ChainTvlSource, extract_chain_tvl
from src.ingestion.defillama.loader import RAW_TABLE, load_chain_tvl
from src.ingestion.merge_loader import new_batch_id

logger = logging.getLogger(__name__)

# The chains of the four tracked assets (ETH, SOL, BNB, BTC), plus DeFi as a whole.
MVP_CHAINS = ("Ethereum", "Solana", "BSC", "Bitcoin", ALL_CHAINS)


@dataclass(frozen=True)
class TvlSyncResult:
    chain: str
    fetched_date: date
    is_backfill: bool
    days_received: int
    rows_inserted: int
    rows_updated: int


def has_history(conn: Any, chain: str, table: str = RAW_TABLE) -> bool:
    """Has this chain been loaded before? If not, this run is its backfill."""

    sql = f"SELECT COUNT(*) FROM {table} WHERE chain = %(chain)s"
    try:
        with conn.cursor() as cur:
            return cur.execute(sql, {"chain": chain}).fetchone()[0] > 0
    except SnowflakeDriverError as err:
        raise WarehouseError(f"Reading {chain} history from {table} failed: {err}") from err


def sync_chain(
    source: ChainTvlSource, conn: Any, chain: str, today: date | None = None
) -> TvlSyncResult:
    today = today or datetime.now(UTC).date()
    backfill = not has_history(conn, chain)
    points = extract_chain_tvl(source, chain, today)
    result = load_chain_tvl(conn, points, today, backfill, new_batch_id())
    summary = TvlSyncResult(
        chain, today, backfill, len(points), result.rows_inserted, result.rows_updated
    )
    logger.info(
        "%s TVL%s: %d day(s) received, %d new or revised, %d corrected",
        chain,
        " (backfill)" if backfill else "",
        summary.days_received,
        summary.rows_inserted,
        summary.rows_updated,
    )
    return summary
