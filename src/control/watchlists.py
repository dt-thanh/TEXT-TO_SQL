"""Named watchlists of the owner in CONTROL.WATCHLIST (spec v1.1, 3.7, 3.9).

At most MAX_WATCHLISTS lists of MAX_SYMBOLS each. With no watchlist saved yet, `default` is the
four core assets. Removing a symbol from a list never deletes its data (DYN-07).
"""

import re
from datetime import UTC, datetime

from src.control.assets import CONTROL, AssetError, Warehouse, core_symbols

MAX_WATCHLISTS = 3
MAX_SYMBOLS = 10
DEFAULT = "default"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")


def check_name(name: str) -> str:
    value = name.strip().lower()
    if not NAME_PATTERN.match(value):
        raise AssetError("a watchlist name is 1-30 letters, digits, - or _", "invalid")
    return value


def all_watchlists(client: Warehouse) -> dict[str, list[str]]:
    rows = client.execute(
        f"SELECT watchlist_name, symbol FROM {CONTROL}.WATCHLIST "
        "ORDER BY watchlist_name, added_at, symbol"
    )
    lists: dict[str, list[str]] = {}
    for row in rows:
        lists.setdefault(row["WATCHLIST_NAME"], []).append(row["SYMBOL"])
    return lists or {DEFAULT: list(core_symbols())}


def get_watchlist(client: Warehouse, name: str) -> list[str]:
    name = check_name(name)
    lists = all_watchlists(client)
    if name not in lists:
        raise AssetError(f"no watchlist named {name!r}", "not_found")
    return lists[name]


def save_watchlist(
    client: Warehouse, name: str, symbols: list[str], now: datetime | None = None
) -> list[str]:
    """Replace the list's symbols. Symbols must already be normalized pairs."""

    name = check_name(name)
    symbols = list(dict.fromkeys(symbols))
    if not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise AssetError(f"a watchlist holds 1 to {MAX_SYMBOLS} assets", "limit")
    rows = client.execute(f"SELECT DISTINCT watchlist_name FROM {CONTROL}.WATCHLIST")
    names = {row["WATCHLIST_NAME"] for row in rows}
    if name not in names and len(names) >= MAX_WATCHLISTS:
        raise AssetError(f"at most {MAX_WATCHLISTS} watchlists", "limit")

    now = now or datetime.now(UTC)
    params = {"name": name, "now": now, **{f"s{i}": s for i, s in enumerate(symbols)}}
    keep = ", ".join(f"%(s{i})s" for i in range(len(symbols)))
    client.execute(
        f"DELETE FROM {CONTROL}.WATCHLIST "
        f"WHERE watchlist_name = %(name)s AND symbol NOT IN ({keep})",
        params,
    )
    values = " UNION ALL ".join(f"SELECT %(s{i})s AS symbol" for i in range(len(symbols)))
    client.execute(
        f"""
MERGE INTO {CONTROL}.WATCHLIST AS t
USING ({values}) AS s ON t.watchlist_name = %(name)s AND t.symbol = s.symbol
WHEN NOT MATCHED THEN INSERT (watchlist_name, symbol, added_at) VALUES (%(name)s, s.symbol, %(now)s)
""",
        params,
    )
    return symbols


def delete_watchlist(client: Warehouse, name: str) -> None:
    client.execute(
        f"DELETE FROM {CONTROL}.WATCHLIST WHERE watchlist_name = %(name)s",
        {"name": check_name(name)},
    )
