"""Unit tests for the cached schema context (metadata read at most once per TTL)."""

from typing import Any

from src.agents.tools.schema_tools import SCHEMA_TTL_SECONDS, get_schema_context

METADATA = [
    {"TABLE_NAME": "MART_ASSET_DAILY", "TABLE_COMMENT": "One row per asset per day.",
     "COLUMN_NAME": "CLOSE_PRICE", "DATA_TYPE": "NUMBER", "COLUMN_COMMENT": ""},
]  # fmt: skip


class CountingWarehouse:
    def __init__(self) -> None:
        self.queries = 0

    def execute(self, sql: str, params: Any = None, max_rows: int | None = None) -> list[Any]:
        self.queries += 1
        return METADATA


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_metadata_is_read_once_and_reused_until_it_is_old() -> None:
    # The MART schema changes once a day at most; reading INFORMATION_SCHEMA costs 1-2 s.
    warehouse, clock = CountingWarehouse(), Clock()

    first = get_schema_context(warehouse, clock=clock)
    clock.now += SCHEMA_TTL_SECONDS - 1
    second = get_schema_context(warehouse, clock=clock)

    assert second is first and warehouse.queries == 1

    clock.now += 2  # now older than the TTL
    get_schema_context(warehouse, clock=clock)

    assert warehouse.queries == 2


def test_each_warehouse_connection_has_its_own_cache() -> None:
    one, two = CountingWarehouse(), CountingWarehouse()

    get_schema_context(one)
    get_schema_context(two)

    assert one.queries == 1 and two.queries == 1
