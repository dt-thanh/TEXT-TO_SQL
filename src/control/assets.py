"""The asset universe: the four core assets plus the coins the owner added (spec v1.1, 3.7-3.9).

Core assets come from dbt/seeds/binance_assets.csv (history since 2019). Any other USDT spot pair
that Binance trades can be requested; a request only writes a row in CONTROL.ASSET_REGISTRY. The
onboarding job (src/control/onboarding.py, run by Airflow) does the slow part: it checks the pair
with Binance, backfills its candles with the existing loader and marks it ready once MART has it.

Registry status: requested -> validating -> backfilling -> ready, or unsupported (not a USDT spot
pair that is trading), error (failed 3 times, retry by hand) and disabled (switched off by the
owner). The status shown to the owner folds these into ready / loading / stale / unsupported /
error / disabled.

`client` is anything with execute(sql, params) -> list of dict rows, like SnowflakeClient.
"""

import csv
import difflib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from src.common.exceptions import FinSightError, WarehouseError

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parents[2]
CORE_ASSETS_SEED = PROJECT_DIR / "dbt" / "seeds" / "binance_assets.csv"

CONTROL = "FINSIGHT.CONTROL"
QUOTE_ASSET = "USDT"
EXCHANGE = "BINANCE"

MAX_ACTIVE_ASSETS = 20  # core + registry assets that are loaded or being loaded
MAX_REQUESTS_PER_DAY = 10  # stops a looping script, not the owner
DEFAULT_BACKFILL_DAYS = 365
MAX_BACKFILL_DAYS = 730
MAX_ATTEMPTS = 3  # automatic tries before an asset stays in `error`
STALE_AFTER_DAYS = 2  # newest daily row older than this many days -> `stale`

LOADING = ("requested", "validating", "backfilling")
# Statuses that count toward MAX_ACTIVE_ASSETS: loaded daily, or about to be.
ACTIVE = (*LOADING, "ready", "error")

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{1,20}USDT$")


class AssetError(FinSightError):
    """A request about an asset that cannot be done; `kind` maps to an HTTP status."""

    def __init__(self, message: str, kind: str) -> None:
        super().__init__(message)
        self.kind = kind  # invalid | unsupported | limit | rate | not_found


class Warehouse(Protocol):
    def execute(
        self, sql: str, params: dict[str, Any] | None = None, max_rows: int | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class CoreAsset:
    symbol: str
    base_asset: str
    name: str


def core_assets(seed: Path = CORE_ASSETS_SEED) -> tuple[CoreAsset, ...]:
    """The assets with full history, from the same seed that builds dim_asset."""

    with seed.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return tuple(CoreAsset(r["symbol"], r["base_asset"], r["asset_name"]) for r in rows)


def core_symbols() -> tuple[str, ...]:
    return tuple(asset.symbol for asset in core_assets())


def normalize_symbol(text: str) -> str:
    """'link', 'LINK', 'linkusdt', ' LINKUSDT ' -> 'LINKUSDT'; anything else is invalid.

    Only letters and digits get through, so a symbol can never carry SQL or prompt text.
    """

    value = text.strip().upper()
    if value and not value.endswith(QUOTE_ASSET):
        value += QUOTE_ASSET
    if not SYMBOL_PATTERN.match(value) or value == QUOTE_ASSET:
        raise AssetError(f"{text!r} is not a Binance USDT pair such as LINKUSDT", "invalid")
    return value


def display_status(registry_status: str, data_through: date | None, today: date) -> str:
    """What the owner sees for one asset."""

    if registry_status in LOADING:
        return "loading"
    if registry_status != "ready":
        return registry_status  # unsupported, error, disabled
    if data_through is None or (today - data_through).days > STALE_AFTER_DAYS:
        return "stale"
    return "ready"


# --- Binance symbol catalog ----------------------------------------------------------------


def catalog_entry(client: Warehouse, symbol: str) -> dict[str, Any] | None:
    rows = client.execute(
        f"SELECT symbol, base_asset FROM {CONTROL}.BINANCE_SYMBOL WHERE symbol = %(symbol)s",
        {"symbol": symbol},
    )
    return rows[0] if rows else None


def search_catalog(client: Warehouse, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Pairs whose symbol starts with the query, with their registry status if any."""

    prefix = re.sub(r"[^A-Z0-9]", "", query.upper())[:20]
    if not prefix:
        return []
    return client.execute(
        f"""
SELECT c.symbol, c.base_asset, r.status, r.data_through, r.last_error
FROM {CONTROL}.BINANCE_SYMBOL AS c
LEFT JOIN {CONTROL}.ASSET_REGISTRY AS r ON r.symbol = c.symbol
WHERE STARTSWITH(c.symbol, %(prefix)s) OR STARTSWITH(c.base_asset, %(prefix)s)
ORDER BY (c.base_asset = %(prefix)s) DESC, LENGTH(c.symbol), c.symbol
LIMIT {int(limit)}
""",
        {"prefix": prefix},
    )


# --- Registry --------------------------------------------------------------------------------


MAX_CHECK = 20  # coins checked in one go


def split_input(text: str) -> list[str]:
    """'link, avax;ARB  btcusdt' -> ['link', 'avax', 'ARB', 'btcusdt'] (order kept, no repeats)."""

    return list(dict.fromkeys(part for part in re.split(r"[\s,;]+", text.strip()) if part))


def suggestions(word: str, bases: list[str], limit: int = 3) -> list[str]:
    """Pairs the owner may have meant: tickers that start with what was typed, then look-alikes
    (ARBB -> ARB, ETHH -> ETH, SOLANA -> SOL)."""

    base = re.sub(r"[^A-Z0-9]", "", word.upper())
    base = base[: -len(QUOTE_ASSET)] if base.endswith(QUOTE_ASSET) and base != QUOTE_ASSET else base
    if not base:
        return []
    starts = sorted((b for b in bases if b.startswith(base) and b != base), key=len)
    prefix = sorted((b for b in bases if base.startswith(b) and len(b) >= 2), key=len, reverse=True)
    close = difflib.get_close_matches(base, bases, n=limit, cutoff=0.6)
    picked = list(dict.fromkeys([*close, *prefix, *starts]))[:limit]
    return [f"{b}{QUOTE_ASSET}" for b in picked]


def check_symbols(client: Warehouse, texts: list[str]) -> list[dict[str, Any]]:
    """For each coin as typed: is it a USDT spot pair Binance trades, and what would adding it do?

    Nothing is written. Each result has `input`, `symbol` (normalized, or None), `ok`, `action`
    (core | already_added | add | none) and `message`; a wrong coin gets `suggestions`.
    """

    if len(texts) > MAX_CHECK:
        raise AssetError(f"check at most {MAX_CHECK} coins at once", "limit")
    catalog = client.execute(f"SELECT symbol, base_asset FROM {CONTROL}.BINANCE_SYMBOL")
    trading = {row["SYMBOL"]: row["BASE_ASSET"] for row in catalog}
    bases = sorted(set(trading.values()))
    added = {
        row["SYMBOL"]: row["STATUS"]
        for row in client.execute(f"SELECT symbol, status FROM {CONTROL}.ASSET_REGISTRY")
    }
    results = []
    for text in texts:
        result: dict[str, Any] = {"input": text, "symbol": None, "ok": False, "action": "none"}
        try:
            symbol = normalize_symbol(text)
        except AssetError:
            result["message"] = "not a ticker: use letters and digits, e.g. LINK or LINKUSDT"
            result["suggestions"] = suggestions(text, bases)
            results.append(result)
            continue
        result["symbol"] = symbol
        if symbol in core_symbols():
            result.update(ok=True, action="core", message="core asset, history since 2019")
        elif symbol not in trading:
            result["message"] = "not a USDT spot pair trading on Binance"
            result["suggestions"] = suggestions(symbol, bases)
        elif added.get(symbol) in (*LOADING, "ready"):
            result.update(
                ok=True, action="already_added", message=f"already added ({added[symbol]})"
            )
        else:
            again = " again" if symbol in added else ""
            result.update(ok=True, action="add", message=f"on Binance: will be added{again}")
        results.append(result)
    return results


def registry_row(client: Warehouse, symbol: str) -> dict[str, Any] | None:
    rows = client.execute(
        f"SELECT * FROM {CONTROL}.ASSET_REGISTRY WHERE symbol = %(symbol)s", {"symbol": symbol}
    )
    return rows[0] if rows else None


def request_asset(
    client: Warehouse,
    symbol: str,
    now: datetime | None = None,
    backfill_days: int = DEFAULT_BACKFILL_DAYS,
) -> str:
    """Make sure `symbol` is or will be loaded; return its registry status after the request.

    Idempotent: asking twice for the same pair leaves one registry row and one onboarding job.
    Raises AssetError for a pair Binance does not trade, or when a limit would be passed.
    """

    now = now or datetime.now(UTC)
    if symbol in core_symbols():
        return "ready"
    if not 1 <= backfill_days <= MAX_BACKFILL_DAYS:
        raise AssetError(f"backfill must be 1 to {MAX_BACKFILL_DAYS} days", "invalid")

    existing = registry_row(client, symbol)
    if existing and existing["STATUS"] != "disabled":
        return existing["STATUS"]

    entry = catalog_entry(client, symbol)
    if entry is None:
        raise AssetError(f"{symbol} is not a USDT spot pair trading on Binance", "unsupported")

    counts = client.execute(
        f"""
SELECT
    COUNT_IF(status IN ({", ".join(f"'{s}'" for s in ACTIVE)})) AS active,
    COUNT_IF(requested_at >= %(day_start)s) AS requested_today
FROM {CONTROL}.ASSET_REGISTRY
""",
        {"day_start": now.replace(hour=0, minute=0, second=0, microsecond=0)},
    )[0]
    if len(core_symbols()) + int(counts["ACTIVE"] or 0) >= MAX_ACTIVE_ASSETS:
        raise AssetError(f"at most {MAX_ACTIVE_ASSETS} assets can be tracked", "limit")
    if int(counts["REQUESTED_TODAY"] or 0) >= MAX_REQUESTS_PER_DAY:
        raise AssetError(f"at most {MAX_REQUESTS_PER_DAY} new assets per day", "rate")

    params = {
        "symbol": symbol,
        "asset_key": f"{EXCHANGE}:{entry['BASE_ASSET']}",
        "base_asset": entry["BASE_ASSET"],
        "quote_asset": QUOTE_ASSET,
        "backfill_start": (now - timedelta(days=backfill_days)).date(),
        "now": now,
    }
    # A disabled asset comes back as a new request: onboarding continues from its watermark.
    client.execute(
        f"""
MERGE INTO {CONTROL}.ASSET_REGISTRY AS t
USING (SELECT %(symbol)s AS symbol) AS s ON t.symbol = s.symbol
WHEN MATCHED AND t.status = 'disabled' THEN UPDATE SET
    status = 'requested', attempts = 0, last_error = NULL, claim_id = NULL,
    requested_at = %(now)s, updated_at = %(now)s
WHEN NOT MATCHED THEN INSERT
    (symbol, asset_key, base_asset, quote_asset, display_name, status, backfill_start,
     requested_at, attempts, updated_at)
VALUES
    (%(symbol)s, %(asset_key)s, %(base_asset)s, %(quote_asset)s, %(base_asset)s, 'requested',
     %(backfill_start)s, %(now)s, 0, %(now)s)
""",
        params,
    )
    logger.info("Asset %s requested (backfill from %s)", symbol, params["backfill_start"])
    return "requested"


def retry_asset(client: Warehouse, symbol: str, now: datetime | None = None) -> str:
    """Send an asset in `error` back to onboarding with a fresh set of attempts."""

    row = registry_row(client, symbol)
    if row is None:
        raise AssetError(f"{symbol} was never requested", "not_found")
    if row["STATUS"] != "error":
        return row["STATUS"]
    client.execute(
        f"""
UPDATE {CONTROL}.ASSET_REGISTRY
SET status = 'requested', attempts = 0, claim_id = NULL, updated_at = %(now)s
WHERE symbol = %(symbol)s AND status = 'error'
""",
        {"symbol": symbol, "now": now or datetime.now(UTC)},
    )
    return "requested"


def disable_asset(client: Warehouse, symbol: str, now: datetime | None = None) -> str:
    """Stop loading an asset. Its data stays in RAW and MART; requesting it again resumes."""

    if symbol in core_symbols():
        raise AssetError(f"{symbol} is a core asset and cannot be disabled", "invalid")
    if registry_row(client, symbol) is None:
        raise AssetError(f"{symbol} was never requested", "not_found")
    client.execute(
        f"""
UPDATE {CONTROL}.ASSET_REGISTRY
SET status = 'disabled', claim_id = NULL, updated_at = %(now)s
WHERE symbol = %(symbol)s
""",
        {"symbol": symbol, "now": now or datetime.now(UTC)},
    )
    return "disabled"


def daily_symbols(client: Warehouse, fallback: tuple[str, ...]) -> list[str]:
    """What the daily Binance load covers: core assets plus every ready registry asset.

    Without the CONTROL schema (a fresh setup, an offline test) this is `fallback`, with a warning.
    """

    core = list(core_symbols())
    try:
        rows = client.execute(
            f"SELECT symbol FROM {CONTROL}.ASSET_REGISTRY WHERE status = 'ready' ORDER BY symbol"
        )
    except WarehouseError as err:
        logger.warning("Asset registry not readable, loading the default symbols: %s", err)
        return list(fallback)
    return core + [row["SYMBOL"] for row in rows if row["SYMBOL"] not in core]
