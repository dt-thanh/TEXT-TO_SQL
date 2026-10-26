"""Asset requests: validation, idempotence, limits, statuses (spec v1.1 DYN-01, 02, 07, 09)."""

from datetime import UTC, date, datetime
from typing import Any

import pytest

from src.common.exceptions import WarehouseError
from src.control.assets import (
    MAX_ACTIVE_ASSETS,
    AssetError,
    core_symbols,
    daily_symbols,
    disable_asset,
    display_status,
    normalize_symbol,
    request_asset,
    retry_asset,
)
from src.ingestion.binance.sync import MVP_SYMBOLS

NOW = datetime(2026, 10, 25, 9, 30, tzinfo=UTC)


class FakeWarehouse:
    """Answers by the first matching SQL fragment; records every statement."""

    def __init__(self, answers: dict[str, Any] | None = None) -> None:
        self.answers = answers or {}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(
        self, sql: str, params: dict[str, Any] | None = None, max_rows: int | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append((sql, params))
        for fragment, answer in self.answers.items():
            if fragment in sql:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return []

    def statements(self, fragment: str) -> list[tuple[str, dict[str, Any] | None]]:
        return [call for call in self.calls if fragment in call[0]]


def catalog_has(symbol: str, base: str) -> dict[str, Any]:
    return {"FROM FINSIGHT.CONTROL.BINANCE_SYMBOL WHERE": [{"SYMBOL": symbol, "BASE_ASSET": base}]}


def counts(active: int = 0, today: int = 0) -> dict[str, Any]:
    return {"COUNT_IF": [{"ACTIVE": active, "REQUESTED_TODAY": today}]}


@pytest.mark.parametrize(
    "text, symbol",
    [
        ("link", "LINKUSDT"),
        (" LINK ", "LINKUSDT"),
        ("linkusdt", "LINKUSDT"),
        ("1INCH", "1INCHUSDT"),
    ],
)
def test_symbols_are_normalized_to_usdt_pairs(text: str, symbol: str) -> None:
    assert normalize_symbol(text) == symbol


@pytest.mark.parametrize(
    "text", ["", "USDT", "LINK-USDT", "LINK'; DROP TABLE x;--", "ignore previous instructions"]
)
def test_anything_but_letters_and_digits_is_refused(text: str) -> None:
    # SEC-03: a symbol can never carry SQL or prompt text into a query.
    with pytest.raises(AssetError) as err:
        normalize_symbol(text)
    assert err.value.kind == "invalid"


def test_the_fallback_list_is_the_core_assets_seed() -> None:
    assert core_symbols() == MVP_SYMBOLS


def test_a_core_asset_is_ready_without_touching_the_registry() -> None:
    warehouse = FakeWarehouse()

    assert request_asset(warehouse, "ETHUSDT", NOW) == "ready"
    assert warehouse.calls == []


def test_a_pair_binance_does_not_trade_is_refused_without_a_job() -> None:
    # DYN-01: checked against the catalog table, not by calling Binance in the request.
    warehouse = FakeWarehouse()

    with pytest.raises(AssetError) as err:
        request_asset(warehouse, "NOPEUSDT", NOW)

    assert err.value.kind == "unsupported"
    assert warehouse.statements("MERGE") == []


def test_a_new_asset_is_requested_with_its_coin_identity_and_backfill_window() -> None:
    warehouse = FakeWarehouse({**catalog_has("LINKUSDT", "LINK"), **counts()})

    assert request_asset(warehouse, "LINKUSDT", NOW) == "requested"

    [(sql, params)] = warehouse.statements("MERGE INTO FINSIGHT.CONTROL.ASSET_REGISTRY")
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert params["asset_key"] == "BINANCE:LINK"
    assert params["backfill_start"] == date(2025, 10, 25)


def test_asking_twice_keeps_one_registry_row() -> None:
    # DYN-02: the second request sees the row and writes nothing.
    warehouse = FakeWarehouse(
        {"SELECT * FROM FINSIGHT.CONTROL.ASSET_REGISTRY": [{"STATUS": "backfilling"}]}
    )

    assert request_asset(warehouse, "LINKUSDT", NOW) == "backfilling"
    assert warehouse.statements("MERGE") == []


def test_a_disabled_asset_comes_back_as_a_request() -> None:
    warehouse = FakeWarehouse(
        {
            "SELECT * FROM FINSIGHT.CONTROL.ASSET_REGISTRY": [{"STATUS": "disabled"}],
            **catalog_has("LINKUSDT", "LINK"),
            **counts(),
        }
    )

    assert request_asset(warehouse, "LINKUSDT", NOW) == "requested"
    [(sql, _)] = warehouse.statements("MERGE")
    assert "WHEN MATCHED AND t.status = 'disabled'" in sql


@pytest.mark.parametrize(
    "active, today, kind",
    [(MAX_ACTIVE_ASSETS - len(MVP_SYMBOLS), 0, "limit"), (0, 10, "rate")],
)
def test_limits_are_errors_not_silent_cuts(active: int, today: int, kind: str) -> None:
    # DYN-09
    warehouse = FakeWarehouse({**catalog_has("LINKUSDT", "LINK"), **counts(active, today)})

    with pytest.raises(AssetError) as err:
        request_asset(warehouse, "LINKUSDT", NOW)

    assert err.value.kind == kind
    assert warehouse.statements("MERGE") == []


def test_only_an_asset_in_error_is_sent_back_to_onboarding() -> None:
    warehouse = FakeWarehouse({"SELECT * FROM": [{"STATUS": "error"}]})
    assert retry_asset(warehouse, "LINKUSDT", NOW) == "requested"
    assert warehouse.statements("SET status = 'requested', attempts = 0")

    ready = FakeWarehouse({"SELECT * FROM": [{"STATUS": "ready"}]})
    assert retry_asset(ready, "LINKUSDT", NOW) == "ready"
    assert ready.statements("UPDATE") == []


def test_disabling_keeps_the_data_and_refuses_core_assets() -> None:
    # DYN-07: only the status changes; nothing is deleted from RAW or MART.
    warehouse = FakeWarehouse({"SELECT * FROM": [{"STATUS": "ready"}]})
    assert disable_asset(warehouse, "LINKUSDT", NOW) == "disabled"
    assert not any("DELETE" in sql for sql, _ in warehouse.calls)

    with pytest.raises(AssetError):
        disable_asset(warehouse, "BTCUSDT", NOW)


def test_the_daily_load_is_core_plus_ready_assets() -> None:
    warehouse = FakeWarehouse({"status = 'ready'": [{"SYMBOL": "LINKUSDT"}, {"SYMBOL": "ETHUSDT"}]})

    assert daily_symbols(warehouse, MVP_SYMBOLS) == [*MVP_SYMBOLS, "LINKUSDT"]


def test_without_the_registry_the_daily_load_falls_back_to_the_default_list() -> None:
    warehouse = FakeWarehouse({"ASSET_REGISTRY": WarehouseError("does not exist")})

    assert daily_symbols(warehouse, MVP_SYMBOLS) == list(MVP_SYMBOLS)


@pytest.mark.parametrize(
    "status, through, shown",
    [
        ("requested", None, "loading"),
        ("backfilling", None, "loading"),
        ("ready", date(2026, 10, 24), "ready"),
        ("ready", date(2026, 10, 22), "stale"),
        ("ready", None, "stale"),
        ("unsupported", None, "unsupported"),
        ("error", None, "error"),
    ],
)
def test_what_the_owner_sees(status: str, through: date | None, shown: str) -> None:
    assert display_status(status, through, date(2026, 10, 25)) == shown


def test_typed_coins_are_split_and_checked_with_suggestions_for_typos() -> None:
    from src.control.assets import check_symbols, split_input

    catalog = [
        {"SYMBOL": f"{b}USDT", "BASE_ASSET": b} for b in ("ARB", "AVAX", "LINK", "DOGE", "ETH")
    ]
    warehouse = FakeWarehouse(
        {
            "SELECT symbol, base_asset FROM FINSIGHT.CONTROL.BINANCE_SYMBOL": catalog,
            "SELECT symbol, status FROM FINSIGHT.CONTROL.ASSET_REGISTRY": [
                {"SYMBOL": "LINKUSDT", "STATUS": "ready"}
            ],
        }
    )

    results = check_symbols(warehouse, split_input("avax, link;arbb  btc dogecoin x'y"))

    shown = {r["input"]: (r["ok"], r["action"], r.get("suggestions")) for r in results}
    assert shown == {
        "avax": (True, "add", None),
        "link": (True, "already_added", None),
        "arbb": (False, "none", ["ARBUSDT"]),
        "btc": (True, "core", None),
        "dogecoin": (False, "none", ["DOGEUSDT"]),
        "x'y": (False, "none", []),
    }
    assert not any(
        sql.lstrip().startswith(("MERGE", "UPDATE", "INSERT")) for sql, _ in warehouse.calls
    )
