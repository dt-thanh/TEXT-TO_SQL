"""FinSight Pulse endpoints: assets, watchlists, daily briefs, usage, data health (spec v1.1, 6.2).

Two Snowflake identities, never mixed: CONTROL rows (registry, watchlists, saved briefs, usage)
through the API's own FINSIGHT_APP user; market data through the read-only agent user, like
/ask. No route writes RAW or MART or calls Binance: adding a coin writes a request and starts
the onboarding DAG, which does the slow work.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.agents.research.brief import MAX_COST_USD, BriefAnswer, brief_to_dict, generate_brief
from src.agents.text_to_sql import agent_warehouse
from src.agents.tools.schema_tools import get_schema_context
from src.api.security import note, rate_limit
from src.common.config import get_settings
from src.control import assets as asset_store
from src.control import briefs as brief_store
from src.control import watchlists as watchlist_store
from src.control.airflow_trigger import trigger_dag
from src.control.assets import AssetError, core_symbols, display_status, normalize_symbol
from src.control.usage import BudgetExceeded, CostCap
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)

router = APIRouter()

HTTP_STATUS = {"invalid": 422, "unsupported": 422, "limit": 409, "rate": 429, "not_found": 404}


@lru_cache
def get_control() -> SnowflakeClient:
    """The API's CONTROL-only Snowflake client, one per process (FastAPI dependency)."""

    return SnowflakeClient(
        get_settings().for_app(),
        query_tag="finsight_app",
        statement_timeout_seconds=30,
        keep_connection=True,
    )


def get_agent() -> Any:
    return agent_warehouse()


@lru_cache
def cost_cap() -> CostCap:
    return CostCap(get_control(), get_settings().llm_daily_cost_cap_usd)


def get_cost_cap() -> CostCap:
    return cost_cap()


def get_brief_fn() -> Callable[..., BriefAnswer]:
    return generate_brief


def get_trigger() -> Callable[[], bool]:
    return trigger_dag


Control = Annotated[Any, Depends(get_control)]
Agent = Annotated[Any, Depends(get_agent)]
Cap = Annotated[CostCap, Depends(get_cost_cap)]


def asset_errors(err: AssetError) -> HTTPException:
    return HTTPException(status_code=HTTP_STATUS.get(err.kind, 422), detail=str(err))


def budget_error(err: BudgetExceeded) -> HTTPException:
    return HTTPException(status_code=429, detail=str(err), headers={"Retry-After": "3600"})


# --- Asset status ----------------------------------------------------------------------------


def statuses(control: Any, agent: Any, symbols: list[str]) -> list[dict[str, Any]]:
    """What the owner sees for each symbol: ready, loading, stale, unsupported, error, disabled."""

    today = datetime.now(UTC).date()
    universe = {row["SYMBOL"]: row for row in get_schema_context(agent).universe}
    added = [s for s in symbols if s not in core_symbols()]
    registry = {}
    if added:
        placeholders = ", ".join(f"%(s{i})s" for i in range(len(added)))
        rows = control.execute(
            f"SELECT symbol, status, last_error FROM {asset_store.CONTROL}.ASSET_REGISTRY "
            f"WHERE symbol IN ({placeholders})",
            {f"s{i}": s for i, s in enumerate(added)},
        )
        registry = {row["SYMBOL"]: row for row in rows}
    shown = []
    for symbol in symbols:
        in_mart = universe.get(symbol, {})
        through = in_mart.get("DATA_THROUGH")
        if symbol in core_symbols():
            status, error = "ready", None
        else:
            row = registry.get(symbol, {})
            status, error = row.get("STATUS", "loading"), row.get("LAST_ERROR")
            if status == "ready" and not through:  # MART is rebuilt after the registry
                status = "backfilling"
        shown.append(
            {
                "symbol": symbol,
                "status": display_status(status, through, today),
                "data_from": in_mart.get("DATA_FROM"),
                "data_through": through,
                "error": error if status in ("error", "unsupported") else None,
            }
        )
    return shown


@router.get("/assets/search")
def search_assets(
    control: Control, q: Annotated[str, Query(min_length=1, max_length=20)]
) -> list[dict[str, Any]]:
    """USDT spot pairs Binance trades whose symbol or ticker starts with q (at most 20)."""

    today = datetime.now(UTC).date()
    rows = asset_store.search_catalog(control, q)
    return [
        {
            "symbol": row["SYMBOL"],
            "base_asset": row["BASE_ASSET"],
            "status": "ready"
            if row["SYMBOL"] in core_symbols()
            else display_status(row["STATUS"], row["DATA_THROUGH"], today)
            if row["STATUS"]
            else "not_added",
        }
        for row in rows
    ]


@router.get("/assets/{symbol}")
def get_asset(symbol: str, control: Control, agent: Agent) -> dict[str, Any]:
    try:
        return statuses(control, agent, [normalize_symbol(symbol)])[0]
    except AssetError as err:
        raise asset_errors(err) from err


@router.post("/assets/{symbol}/retry")
def retry_asset(
    symbol: str, control: Control, trigger: Annotated[Callable[[], bool], Depends(get_trigger)]
) -> dict[str, str]:
    try:
        status = asset_store.retry_asset(control, normalize_symbol(symbol))
    except AssetError as err:
        raise asset_errors(err) from err
    if status == "requested":
        trigger()
    return {"symbol": normalize_symbol(symbol), "status": status}


@router.post("/assets/{symbol}/disable")
def disable_asset(symbol: str, control: Control) -> dict[str, str]:
    try:
        return {
            "symbol": normalize_symbol(symbol),
            "status": asset_store.disable_asset(control, normalize_symbol(symbol)),
        }
    except AssetError as err:
        raise asset_errors(err) from err


# --- Watchlists --------------------------------------------------------------------------------


class WatchlistUpdate(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=watchlist_store.MAX_SYMBOLS)


@router.get("/watchlists")
def list_watchlists(control: Control, agent: Agent) -> dict[str, list[dict[str, Any]]]:
    lists = watchlist_store.all_watchlists(control)
    return {name: statuses(control, agent, symbols) for name, symbols in lists.items()}


@router.get("/watchlists/{name}")
def get_watchlist(name: str, control: Control, agent: Agent) -> list[dict[str, Any]]:
    try:
        return statuses(control, agent, watchlist_store.get_watchlist(control, name))
    except AssetError as err:
        raise asset_errors(err) from err


@router.put("/watchlists/{name}", dependencies=[Depends(rate_limit("watchlist_write"))])
def put_watchlist(
    name: str,
    payload: WatchlistUpdate,
    control: Control,
    agent: Agent,
    trigger: Annotated[Callable[[], bool], Depends(get_trigger)],
) -> list[dict[str, Any]]:
    """Replace a watchlist. A coin without data is requested and its onboarding starts now;
    it shows as `loading` until MART has it. Nothing is saved if any symbol is refused."""

    try:
        symbols = list(dict.fromkeys(normalize_symbol(s) for s in payload.symbols))
        for symbol in symbols:  # refuse the whole update before writing anything
            if symbol not in core_symbols() and not asset_store.catalog_entry(control, symbol):
                raise AssetError(
                    f"{symbol} is not a USDT spot pair trading on Binance", "unsupported"
                )
        requested = [s for s in symbols if asset_store.request_asset(control, s) == "requested"]
        watchlist_store.save_watchlist(control, name, symbols)
    except AssetError as err:
        raise asset_errors(err) from err
    if requested:
        trigger()
    return statuses(control, agent, symbols)


class CoinsInput(BaseModel):
    """Coins as the owner types them: 'link, avax arb' or 'LINKUSDT'."""

    text: str = Field(min_length=1, max_length=400)


@router.post("/assets/check")
def check_assets(payload: CoinsInput, control: Control) -> list[dict[str, Any]]:
    """Check coins without saving anything: on Binance or not, what adding would do, and what
    was probably meant when a coin is wrong (ARBB -> ARBUSDT)."""

    try:
        return asset_store.check_symbols(control, asset_store.split_input(payload.text))
    except AssetError as err:
        raise asset_errors(err) from err


@router.post("/watchlists/{name}/add", dependencies=[Depends(rate_limit("watchlist_write"))])
def add_to_watchlist(
    name: str,
    payload: CoinsInput,
    control: Control,
    agent: Agent,
    trigger: Annotated[Callable[[], bool], Depends(get_trigger)],
) -> dict[str, Any]:
    """Add the coins that are right, report the ones that are not. A wrong coin, or one past a
    limit, never blocks the others; each result says what happened to it."""

    try:
        name = watchlist_store.check_name(name)
        results = asset_store.check_symbols(control, asset_store.split_input(payload.text))
        lists = watchlist_store.all_watchlists(control)
    except AssetError as err:
        raise asset_errors(err) from err
    symbols = list(lists.get(name, []))
    requested = False
    for result in results:
        if not result["ok"]:
            continue
        symbol = result["symbol"]
        if symbol in symbols:
            result.update(action="already_in_watchlist", message="already in this watchlist")
            continue
        if len(symbols) >= watchlist_store.MAX_SYMBOLS:
            full = f"watchlist full ({watchlist_store.MAX_SYMBOLS} coins)"
            result.update(ok=False, action="none", message=full)
            continue
        try:
            status = asset_store.request_asset(control, symbol)
        except AssetError as err:  # 20 assets, or 10 new ones today
            result.update(ok=False, action="none", message=str(err))
            continue
        requested = requested or status == "requested"
        symbols.append(symbol)
        result["message"] = {"requested": "added: loading history (a few minutes)"}.get(
            status, f"added ({status})"
        )
    changed = symbols != lists.get(name, [])
    if changed:
        try:
            watchlist_store.save_watchlist(control, name, symbols)
        except AssetError as err:
            raise asset_errors(err) from err
    if requested:
        trigger()
    return {"results": results, "watchlist": statuses(control, agent, symbols) if symbols else []}


@router.delete("/watchlists/{name}", status_code=204)
def delete_watchlist(name: str, control: Control) -> None:
    try:
        watchlist_store.delete_watchlist(control, name)
    except AssetError as err:
        raise asset_errors(err) from err


# --- Briefs -------------------------------------------------------------------------------------


class BriefRequest(BaseModel):
    watchlist: str | None = None
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=10)
    window_days: int = Field(default=30, ge=7, le=365)
    language: Literal["en", "vi"] = "en"
    use_llm: bool = True


@router.post("/brief", dependencies=[Depends(rate_limit("brief"))])
def make_brief(
    payload: BriefRequest,
    control: Control,
    cap: Cap,
    brief_fn: Annotated[Callable[..., BriefAnswer], Depends(get_brief_fn)],
) -> dict[str, Any]:
    """A Daily Brief now, for a saved watchlist or a list of symbols. Saved when it is for a
    watchlist. A plain `def`: the work blocks for up to 90 s."""

    try:
        if payload.watchlist:
            name = watchlist_store.check_name(payload.watchlist)
            symbols = watchlist_store.get_watchlist(control, name)
        elif payload.symbols:
            name, symbols = None, [normalize_symbol(s) for s in payload.symbols]
        else:
            raise AssetError("give a watchlist or symbols", "invalid")
    except AssetError as err:
        raise asset_errors(err) from err

    def run(use_llm: bool) -> BriefAnswer:
        return brief_fn(symbols, payload.window_days, name, payload.language, use_llm)

    try:
        if payload.use_llm:
            with cap.reserve(MAX_COST_USD) as record:
                brief = run(True)
                record(brief.research.usage.cost_usd)
        else:
            brief = run(False)
    except BudgetExceeded as err:
        raise budget_error(err) from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err

    note(
        status=brief.status,
        cost_usd=brief.research.usage.cost_usd,
        sql_count=len(brief.research.plan),
    )
    if name:
        now = datetime.now(UTC)
        brief_store.save_brief(
            control, now.date(), name, payload.window_days, brief.status, brief.markdown,
            brief_to_dict(brief), brief.research.usage.cost_usd, brief.research.seconds,
            brief.research.data_as_of, now,
        )  # fmt: skip
    return brief_to_dict(brief)


@router.get("/briefs")
def list_briefs(
    control: Control,
    watchlist: str | None = None,
    limit: Annotated[int, Query(ge=1, le=60)] = 14,
) -> list[dict[str, Any]]:
    name = watchlist_store.check_name(watchlist) if watchlist else None
    return [
        {k.lower(): v for k, v in row.items()}
        for row in brief_store.list_briefs(control, name, limit)
    ]


@router.get("/briefs/{brief_date}")
def get_brief(brief_date: date, control: Control, watchlist: str = "default") -> dict[str, Any]:
    row = brief_store.get_brief(control, brief_date, watchlist_store.check_name(watchlist))
    if row is None:
        raise HTTPException(status_code=404, detail="no brief for that day and watchlist")
    return {k.lower(): v for k, v in row.items()}


# --- Usage and data health ------------------------------------------------------------------

HEALTH_SQL = """
select
    (select max(trade_date)       from FINSIGHT.MART.MART_ASSET_DAILY)     as prices_through,
    (select max(market_date)      from FINSIGHT.MART.MART_MACRO_DAILY)     as macro_through,
    (select max(treasury_10y_source_date) from FINSIGHT.MART.MART_MACRO_DAILY) as treasury_source,
    (select max(tvl_date)         from FINSIGHT.MART.MART_CHAIN_TVL_DAILY) as tvl_through,
    (select max(cpi_release_date) from FINSIGHT.MART.MART_MACRO_DAILY)     as cpi_released
"""


@router.get("/usage/today")
def usage_today(cap: Cap) -> dict[str, float]:
    return cap.status()


@router.get("/health/data")
def data_health(control: Control, agent: Agent, cap: Cap) -> dict[str, Any]:
    """How recent each source is, whether today's brief exists, assets that need attention."""

    today = datetime.now(UTC).date()
    sources = {k.lower(): v for k, v in agent.execute(HEALTH_SQL)[0].items()}
    behind = (today - sources["prices_through"]).days - 1 if sources.get("prices_through") else None
    problems = control.execute(
        f"SELECT symbol, status, last_error FROM {asset_store.CONTROL}.ASSET_REGISTRY "
        "WHERE status IN ('error', 'unsupported') ORDER BY updated_at DESC LIMIT 20"
    )
    briefs = control.execute(
        f"SELECT watchlist_name, status FROM {asset_store.CONTROL}.DAILY_BRIEF "
        "WHERE brief_date = %(day)s",
        {"day": today},
    )
    return {
        "today": today,
        "sources": sources,
        "prices_days_behind": behind,
        "data_ok": behind is not None and behind <= 1,
        "briefs_today": {row["WATCHLIST_NAME"]: row["STATUS"] for row in briefs},
        "assets_needing_attention": [{k.lower(): v for k, v in r.items()} for r in problems],
        "llm_usage": cap.status(),
    }
