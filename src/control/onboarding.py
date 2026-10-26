"""Onboard requested assets: verify with Binance, backfill candles, mark ready (spec v1.1, 3.8).

Run by the Airflow DAG finsight_asset_onboarding in three steps, so dbt runs in between:

    load      claim up to BATCH_SIZE requested assets, verify each pair, backfill its candles
              with the existing loader (closed candles, month windows, MERGE) -> `backfilling`
    (dbt build of the Binance models)
    finalize  every `backfilling` asset that now has rows in MART -> `ready`

The registry status is the hand-off between the steps; nothing is passed through Airflow.
Claiming is an UPDATE guarded by the old status, so two runs cannot take the same asset, and a
claim older than CLAIM_TIMEOUT (a crashed run) can be taken again. A failure counts an attempt:
the asset goes back to `requested` until MAX_ATTEMPTS, then stays in `error`.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Protocol
from uuid import uuid4

from src.common.exceptions import FinSightError, SourceAPIError
from src.control.assets import CONTROL, MAX_ATTEMPTS, QUOTE_ASSET, Warehouse
from src.ingestion.binance.sync import SyncResult, get_watermark, incremental_start, load_window
from src.ingestion.merge_loader import TableSpec, merge_rows, new_batch_id

logger = logging.getLogger(__name__)

BATCH_SIZE = 3  # assets per run: one 365-day backfill is about 9 kline requests
CLAIM_TIMEOUT = timedelta(hours=2)
MIN_CATALOG_PAIRS = 100  # a smaller answer is a broken response, not Binance delisting everything


class BinanceInfo(Protocol):
    def get_exchange_info(self, symbol: str | None = None) -> dict[str, Any]: ...


@dataclass(frozen=True)
class Claimed:
    symbol: str
    backfill_start: date


def is_usdt_spot_trading(info: dict[str, Any]) -> bool:
    return (
        info.get("status") == "TRADING"
        and info.get("quoteAsset") == QUOTE_ASSET
        and bool(info.get("isSpotTradingAllowed"))
    )


# --- Binance symbol catalog (daily) -----------------------------------------------------------

CATALOG_SPEC = TableSpec(
    target_table=f"{CONTROL}.BINANCE_SYMBOL",
    stage_table=f"{CONTROL}.TMP_BINANCE_SYMBOL_LOAD",
    key_columns=("symbol",),
    value_columns=("base_asset", "quote_asset", "status", "is_spot"),
    metadata_columns=("refreshed_at",),
    dedupe_order_by="refreshed_at DESC",
)


def catalog_rows(exchange_info: dict[str, Any], now: datetime) -> list[tuple[Any, ...]]:
    pairs = [s for s in exchange_info.get("symbols", []) if is_usdt_spot_trading(s)]
    return [(s["symbol"], s["baseAsset"], s["quoteAsset"], s["status"], True, now) for s in pairs]


def refresh_catalog(binance: BinanceInfo, conn: Any, now: datetime | None = None) -> int:
    """Replace CONTROL.BINANCE_SYMBOL with Binance's current USDT spot pairs; return the count.

    A pair that stopped trading is removed. A suspiciously small answer changes nothing.
    """

    now = now or datetime.now(UTC)
    rows = catalog_rows(binance.get_exchange_info(), now)
    if len(rows) < MIN_CATALOG_PAIRS:
        raise SourceAPIError(f"Binance listed only {len(rows)} USDT spot pairs; catalog kept")
    merge_rows(conn, CATALOG_SPEC, rows, new_batch_id())
    # Remove pairs missing from this answer (no longer trading). Compared with the stage table
    # of this load, not with refreshed_at: the MERGE leaves an unchanged pair's refreshed_at
    # as it was, so "older than now" would delete every pair on the second refresh (it did,
    # 2026-10-26).
    with conn.cursor() as cur:
        cur.execute(
            f"DELETE FROM {CONTROL}.BINANCE_SYMBOL WHERE symbol NOT IN "
            f"(SELECT symbol FROM {CATALOG_SPEC.stage_table})"
        )
    logger.info("Binance catalog: %d USDT spot pairs", len(rows))
    return len(rows)


# --- Onboarding --------------------------------------------------------------------------------


def claim(
    client: Warehouse, now: datetime, limit: int = BATCH_SIZE, claim_id: str | None = None
) -> list[Claimed]:
    """Take up to `limit` requested assets (oldest request first) for this run."""

    claim_id = claim_id or uuid4().hex
    claimable = (
        "(status = 'requested' OR (status IN ('validating', 'backfilling') "
        "AND updated_at < %(stale_before)s))"
    )
    params = {"claim": claim_id, "now": now, "stale_before": now - CLAIM_TIMEOUT}
    client.execute(
        f"""
UPDATE {CONTROL}.ASSET_REGISTRY
SET status = 'validating', claim_id = %(claim)s, updated_at = %(now)s
WHERE {claimable}
  AND symbol IN (
      SELECT symbol FROM {CONTROL}.ASSET_REGISTRY
      WHERE {claimable}
      ORDER BY requested_at, symbol
      LIMIT {int(limit)}
  )
""",
        params,
    )
    rows = client.execute(
        f"""
SELECT symbol, backfill_start FROM {CONTROL}.ASSET_REGISTRY
WHERE claim_id = %(claim)s AND status = 'validating'
ORDER BY requested_at, symbol
""",
        {"claim": claim_id},
    )
    return [Claimed(row["SYMBOL"], row["BACKFILL_START"]) for row in rows]


def set_status(client: Warehouse, symbol: str, status: str, now: datetime, **fields: Any) -> None:
    assignments = ", ".join(f"{name} = %({name})s" for name in fields)
    extra = f", {assignments}" if assignments else ""
    client.execute(
        f"UPDATE {CONTROL}.ASSET_REGISTRY SET status = %(status)s, updated_at = %(now)s{extra} "
        "WHERE symbol = %(symbol)s",
        {"symbol": symbol, "status": status, "now": now, **fields},
    )


def record_failure(client: Warehouse, symbol: str, error: str, now: datetime) -> str:
    """Count a failed attempt; return the new status (`requested` to retry, or `error`)."""

    rows = client.execute(
        f"SELECT attempts FROM {CONTROL}.ASSET_REGISTRY WHERE symbol = %(symbol)s",
        {"symbol": symbol},
    )
    attempts = int(rows[0]["ATTEMPTS"] or 0) + 1 if rows else 1
    status = "requested" if attempts < MAX_ATTEMPTS else "error"
    set_status(
        client, symbol, status, now, attempts=attempts, last_error=error[:1000], claim_id=None
    )
    logger.warning("Onboarding %s failed (attempt %d): %s", symbol, attempts, error[:300])
    return status


def verify(binance: BinanceInfo, symbol: str) -> bool:
    """Is the pair a USDT spot pair trading now? An unknown symbol is False, not an error."""

    try:
        info = binance.get_exchange_info(symbol)
    except SourceAPIError as err:
        if err.status_code == 400:  # Binance -1121 "Invalid symbol"
            return False
        raise
    pairs = info.get("symbols", [])
    return len(pairs) == 1 and pairs[0].get("symbol") == symbol and is_usdt_spot_trading(pairs[0])


def backfill(
    binance: Any, conn: Any, item: Claimed, now: datetime, interval: str = "1h"
) -> SyncResult:
    """Load the candles the asset is missing: from the watermark if RAW has some, else from
    backfill_start. Same code path as the daily load, so it is idempotent."""

    watermark = get_watermark(conn, item.symbol, interval)
    start = (
        incremental_start(watermark)
        if watermark
        else datetime.combine(item.backfill_start, time(), tzinfo=UTC)
    )
    return load_window(binance, conn, item.symbol, interval, start, now, now)


def load_claimed(
    binance: Any, client: Warehouse, conn: Any, now: datetime | None = None
) -> list[str]:
    """Step 1. Returns the symbols now `backfilling` (empty: nothing to do this run)."""

    now = now or datetime.now(UTC)
    loaded = []
    for item in claim(client, now):
        try:
            if not verify(binance, item.symbol):
                set_status(
                    client,
                    item.symbol,
                    "unsupported",
                    now,
                    claim_id=None,
                    last_error="not a USDT spot pair trading on Binance",
                )
                continue
            set_status(client, item.symbol, "backfilling", now)
            result = backfill(binance, conn, item, now)
        except FinSightError as err:
            record_failure(client, item.symbol, str(err), now)
            continue
        if result.rows_received == 0:
            record_failure(client, item.symbol, "Binance returned no closed candles", now)
            continue
        loaded.append(item.symbol)
    return loaded


def finalize(client: Warehouse, now: datetime | None = None) -> dict[str, str]:
    """Step 3, after dbt: `backfilling` assets with daily rows in MART become `ready`."""

    now = now or datetime.now(UTC)
    rows = client.execute(
        f"""
SELECT r.symbol, MAX(m.trade_date) AS data_through
FROM {CONTROL}.ASSET_REGISTRY AS r
LEFT JOIN FINSIGHT.MART.MART_ASSET_DAILY AS m ON m.symbol = r.symbol
WHERE r.status = 'backfilling'
GROUP BY r.symbol
"""
    )
    outcome = {}
    for row in rows:
        symbol, through = row["SYMBOL"], row["DATA_THROUGH"]
        if through is None:
            outcome[symbol] = record_failure(
                client, symbol, "no daily rows in MART after the dbt build", now
            )
            continue
        set_status(
            client,
            symbol,
            "ready",
            now,
            ready_at=now,
            data_through=through,
            claim_id=None,
            last_error=None,
        )
        outcome[symbol] = "ready"
        logger.info("Asset %s ready, data through %s", symbol, through)
    return outcome
