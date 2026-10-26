"""Unit tests for DefiLlama ingestion: client request, parsing rules, versioned load, sync.

The fixture is a trimmed copy of a real /v2/historicalChainTvl/Ethereum response taken on
2026-10-22: three leading zero days, the first tracked days, and the newest four days (the last
one dated "today").
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from src.common.exceptions import SourceAPIError
from src.ingestion.defillama.client import ALL_CHAINS, DefiLlamaClient
from src.ingestion.defillama.extractor import extract_chain_tvl, parse_series
from src.ingestion.defillama.loader import (
    RAW_TABLE,
    STAGE_TABLE,
    TVL_SPEC,
    build_versioned_merge_sql,
    load_chain_tvl,
)
from src.ingestion.defillama.sync import sync_chain

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "defillama_ethereum_tvl.json"
RAW_POINTS = json.loads(FIXTURE.read_text())
TODAY = date(2026, 10, 22)


# --- Client ----------------------------------------------------------------------------------


def client_for(requests: list[httpx.Request]) -> DefiLlamaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=RAW_POINTS)

    http = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://llama.test")
    return DefiLlamaClient(http=http, sleep=lambda s: None)


def test_one_chain_and_all_chains_use_their_own_paths() -> None:
    requests: list[httpx.Request] = []
    client = client_for(requests)

    client.get_chain_tvl("Ethereum")
    client.get_chain_tvl(ALL_CHAINS)

    assert [r.url.path for r in requests] == [
        "/v2/historicalChainTvl/Ethereum",
        "/v2/historicalChainTvl",
    ]


# --- Parsing ---------------------------------------------------------------------------------


def test_leading_zero_days_are_no_data_not_zero_tvl() -> None:
    points = parse_series("Ethereum", RAW_POINTS, TODAY)

    assert points[0].tvl_date == date(2018, 2, 12)
    assert all(p.tvl_usd > 0 for p in points)


def test_todays_unfinished_point_is_dropped() -> None:
    points = parse_series("Ethereum", RAW_POINTS, TODAY)

    assert points[-1].tvl_date == date(2026, 10, 21)
    assert points[-1].tvl_usd == Decimal("50224842407")


def test_a_gap_stays_a_gap() -> None:
    points = parse_series("Ethereum", RAW_POINTS, TODAY)

    days = [p.tvl_date for p in points]
    assert date(2018, 2, 15) not in days  # missing in the source, not filled with 0


@pytest.mark.parametrize(
    "row",
    [{"date": 1792540800 + 3600, "tvl": 1}, {"date": 1792540800, "tvl": -5}, {"tvl": 1}],
    ids=["not-midnight", "negative", "no-date"],
)
def test_malformed_points_are_rejected(row: dict[str, Any]) -> None:
    with pytest.raises(SourceAPIError):
        parse_series("Ethereum", [row], TODAY)


def test_the_same_day_twice_is_rejected() -> None:
    with pytest.raises(SourceAPIError, match="same day twice"):
        parse_series("Ethereum", [RAW_POINTS[3], RAW_POINTS[3]], TODAY)


# --- Loading ---------------------------------------------------------------------------------


class FakeCursor:
    def __init__(self, count: int = 0, merge_result: tuple[int, int] = (0, 0)) -> None:
        self.count = count
        self.merge_result = merge_result
        self.statements: list[str] = []
        self.rows: list[tuple[Any, ...]] = []
        self._last = ""

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def execute(self, sql: str, params: Any = None) -> "FakeCursor":
        self.statements.append(sql)
        self._last = sql
        return self

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        self.statements.append(sql)
        self.rows.extend(rows)

    def fetchone(self) -> tuple[int, ...]:
        return (self.count,) if "COUNT(*)" in self._last else self.merge_result


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


def test_the_merge_keeps_only_new_or_revised_values_compared_with_earlier_fetches() -> None:
    sql = build_versioned_merge_sql(RAW_TABLE)

    assert f"MERGE INTO {RAW_TABLE}" in sql
    assert f"FROM {STAGE_TABLE}" in sql
    # Compared with the newest value from an EARLIER fetch day, so a same-day re-run is a no-op.
    assert f"WHERE fetched_date < (SELECT MAX(fetched_date) FROM {STAGE_TABLE})" in sql
    assert "ORDER BY fetched_date DESC) = 1" in sql
    assert "known.tvl_usd IS NULL" in sql  # a day never seen before
    # The grain includes the fetch day: a revision is a new row, never an overwrite.
    assert "target.fetched_date = source.fetched_date" in sql


def test_rows_carry_the_fetch_day_and_the_backfill_flag() -> None:
    cursor = FakeCursor(merge_result=(5, 0))
    points = parse_series("Ethereum", RAW_POINTS, TODAY)

    result = load_chain_tvl(FakeConnection(cursor), points, TODAY, True, "batch-1")

    row = dict(zip(TVL_SPEC.columns, cursor.rows[0], strict=True))
    assert (row["chain"], row["tvl_date"], row["fetched_date"]) == (
        "Ethereum",
        date(2018, 2, 12),
        TODAY,
    )
    assert row["is_backfill"] is True
    assert (result.rows_received, result.rows_inserted) == (len(points), 5)


def test_the_first_load_of_a_chain_is_a_backfill_and_later_ones_are_not() -> None:
    class Source:
        def get_chain_tvl(self, chain: str) -> list[dict[str, Any]]:
            return RAW_POINTS

    first = sync_chain(Source(), FakeConnection(FakeCursor(count=0)), "Ethereum", TODAY)
    later = sync_chain(Source(), FakeConnection(FakeCursor(count=3000)), "Ethereum", TODAY)

    assert (first.is_backfill, later.is_backfill) == (True, False)
    assert first.days_received == len(extract_chain_tvl(Source(), "Ethereum", TODAY))


def test_the_chains_loaded_are_the_curated_seed_plus_all_chains() -> None:
    from src.ingestion.defillama.sync import MVP_CHAINS

    assert MVP_CHAINS == ("Ethereum", "Solana", "BSC", "Bitcoin", "All")
