"""Daily cost cap (spec v1.1 SEC-02) and named watchlists (DYN-09)."""

import threading
from datetime import UTC, datetime

import pytest

from src.control.assets import AssetError
from src.control.usage import BudgetExceeded, CostCap
from src.control.watchlists import MAX_WATCHLISTS, all_watchlists, check_name, save_watchlist
from src.ingestion.binance.sync import MVP_SYMBOLS
from tests.unit.test_control.test_assets import FakeWarehouse

NOW = datetime(2026, 10, 26, 8, tzinfo=UTC)


def cap(spent: float, cap_usd: float = 1.0) -> CostCap:
    warehouse = FakeWarehouse({"SELECT llm_cost_usd": [{"LLM_COST_USD": spent}]})
    return CostCap(warehouse, cap_usd, clock=lambda: NOW)


def test_a_request_runs_when_the_budget_covers_its_maximum_and_records_the_real_cost() -> None:
    budget = cap(spent=0.5)

    with budget.reserve(0.02) as record:
        record(0.0013)

    [(sql, params)] = budget.client.statements("MERGE INTO FINSIGHT.CONTROL.API_USAGE")
    assert "llm_cost_usd = t.llm_cost_usd + %(cost)s" in sql
    assert params["cost"] == 0.0013 and params["day"] == NOW.date()


def test_no_llm_call_once_the_budget_is_spent() -> None:
    with pytest.raises(BudgetExceeded, match=r"\$0\.9950 of \$1\.00"):
        with cap(spent=0.995).reserve(0.01):
            pytest.fail("must not run")


def test_parallel_requests_cannot_pass_the_cap_together() -> None:
    # Each reservation holds its maximum until it finishes: 3 x $0.01 into $0.025 left.
    budget = cap(spent=0.975)
    started, release = threading.Barrier(3), threading.Event()
    outcomes: list[str] = []

    def request() -> None:
        try:
            with budget.reserve(0.01):
                outcomes.append("ran")
                started.wait(timeout=2)
                release.wait(timeout=2)
        except BudgetExceeded:
            outcomes.append("refused")
            started.wait(timeout=2)

    threads = [threading.Thread(target=request) for _ in range(3)]
    for thread in threads:
        thread.start()
    release.set()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ran", "ran", "refused"]
    assert budget.status()["reserved_usd"] == 0


def test_without_any_saved_watchlist_default_is_the_core_assets() -> None:
    assert all_watchlists(FakeWarehouse()) == {"default": list(MVP_SYMBOLS)}


@pytest.mark.parametrize("name", ["", "has space", "x" * 31, "drop;table"])
def test_watchlist_names_are_short_plain_words(name: str) -> None:
    with pytest.raises(AssetError):
        check_name(name)


def test_a_fourth_watchlist_or_an_eleventh_asset_is_refused() -> None:
    names = [{"WATCHLIST_NAME": f"list{i}"} for i in range(MAX_WATCHLISTS)]
    warehouse = FakeWarehouse({"SELECT DISTINCT watchlist_name": names})

    with pytest.raises(AssetError, match="at most 3"):
        save_watchlist(warehouse, "another", ["BTCUSDT"], NOW)
    with pytest.raises(AssetError, match="1 to 10"):
        save_watchlist(warehouse, "list0", [f"A{i}USDT" for i in range(11)], NOW)
    save_watchlist(warehouse, "list0", ["BTCUSDT", "LINKUSDT"], NOW)  # an existing one: fine


def test_saving_replaces_the_list_without_touching_any_data() -> None:
    warehouse = FakeWarehouse()

    save_watchlist(warehouse, "DeFi", ["ETHUSDT", "LINKUSDT", "ETHUSDT"], NOW)

    delete, merge = warehouse.calls[1], warehouse.calls[2]
    assert "DELETE FROM FINSIGHT.CONTROL.WATCHLIST" in delete[0] and "NOT IN" in delete[0]
    assert delete[1]["name"] == "defi"
    assert "MERGE INTO FINSIGHT.CONTROL.WATCHLIST" in merge[0]
    assert [merge[1]["s0"], merge[1]["s1"]] == ["ETHUSDT", "LINKUSDT"]
    assert not any("RAW" in sql or "MART" in sql for sql, _ in warehouse.calls)
