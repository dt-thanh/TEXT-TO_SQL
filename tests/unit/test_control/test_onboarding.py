"""Onboarding steps and the Binance catalog (spec v1.1 DYN-03, 04, 05, 06, 11)."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from src.common.exceptions import SourceAPIError
from src.control import onboarding
from src.control.onboarding import (
    CLAIM_TIMEOUT,
    Claimed,
    catalog_rows,
    claim,
    finalize,
    load_claimed,
    record_failure,
    refresh_catalog,
    verify,
)
from src.ingestion.binance.sync import SyncResult
from tests.unit.test_control.test_assets import FakeWarehouse

NOW = datetime(2026, 10, 25, 1, 30, tzinfo=UTC)


def pair(symbol: str, base: str, quote: str = "USDT", status: str = "TRADING", spot: bool = True):
    return {
        "symbol": symbol,
        "baseAsset": base,
        "quoteAsset": quote,
        "status": status,
        "isSpotTradingAllowed": spot,
    }


class FakeBinance:
    def __init__(
        self, pairs: dict[str, dict[str, Any]] | None = None, fail: Exception | None = None
    ):
        self.pairs = pairs or {}
        self.fail = fail
        self.asked: list[str | None] = []

    def get_exchange_info(self, symbol: str | None = None) -> dict[str, Any]:
        self.asked.append(symbol)
        if self.fail:
            raise self.fail
        if symbol is None:
            return {"symbols": list(self.pairs.values())}
        if symbol not in self.pairs:
            raise SourceAPIError("Binance returned HTTP 400: Invalid symbol", status_code=400)
        return {"symbols": [self.pairs[symbol]]}


def test_the_catalog_keeps_only_usdt_spot_pairs_that_trade() -> None:
    info = {
        "symbols": [
            pair("LINKUSDT", "LINK"),
            pair("LINKBTC", "LINK", quote="BTC"),
            pair("OLDUSDT", "OLD", status="BREAK"),
            pair("MARGUSDT", "MARG", spot=False),
        ]
    }

    assert [row[0] for row in catalog_rows(info, NOW)] == ["LINKUSDT"]


def test_a_broken_catalog_answer_changes_nothing() -> None:
    binance = FakeBinance({"LINKUSDT": pair("LINKUSDT", "LINK")})

    with pytest.raises(SourceAPIError, match="catalog kept"):
        refresh_catalog(binance, conn=None, now=NOW)


def test_claiming_is_guarded_by_the_old_status_and_takes_stale_claims_again() -> None:
    # DYN-03: the UPDATE only changes rows still claimable, so a second run gets nothing.
    warehouse = FakeWarehouse(
        {
            "WHERE claim_id = %(claim)s": [
                {"SYMBOL": "LINKUSDT", "BACKFILL_START": date(2025, 10, 25)}
            ]
        }
    )

    claimed = claim(warehouse, NOW, claim_id="run-1")

    assert claimed == [Claimed("LINKUSDT", date(2025, 10, 25))]
    sql, params = warehouse.calls[0]
    assert sql.count("status = 'requested' OR") == 2  # the row filter and the subquery
    assert "LIMIT 3" in sql
    assert params["stale_before"] == NOW - CLAIM_TIMEOUT


def test_an_unknown_pair_is_unsupported_not_an_error() -> None:
    assert verify(FakeBinance(), "NOPEUSDT") is False
    assert verify(FakeBinance({"LINKUSDT": pair("LINKUSDT", "LINK")}), "LINKUSDT") is True
    assert verify(FakeBinance({"XUSDT": pair("XUSDT", "X", status="BREAK")}), "XUSDT") is False


def test_binance_being_down_is_an_error_with_a_reason() -> None:
    # DYN-11: retries happen in retrying_http; what is left is a failure with its message.
    with pytest.raises(SourceAPIError):
        verify(FakeBinance(fail=SourceAPIError("Binance failed after 5 attempts: HTTP 503")), "X")


def test_failures_go_back_to_requested_until_the_last_attempt() -> None:
    first = FakeWarehouse({"SELECT attempts": [{"ATTEMPTS": 0}]})
    assert record_failure(first, "LINKUSDT", "boom", NOW) == "requested"

    last = FakeWarehouse({"SELECT attempts": [{"ATTEMPTS": 2}]})
    assert record_failure(last, "LINKUSDT", "boom", NOW) == "error"
    _, params = last.statements("UPDATE")[0]
    assert params["attempts"] == 3 and params["last_error"] == "boom" and params["claim_id"] is None


def test_backfill_starts_at_backfill_start_or_continues_from_the_watermark(monkeypatch) -> None:
    # DYN-04 and DYN-05: the same load_window as the daily run, from the right start.
    windows = []

    def fake_load_window(binance, conn, symbol, interval, start, end, now):
        windows.append(start)
        return SyncResult(symbol, start, end, 1, 10, 10, 0)

    monkeypatch.setattr(onboarding, "load_window", fake_load_window)
    item = Claimed("LINKUSDT", date(2025, 10, 25))

    monkeypatch.setattr(onboarding, "get_watermark", lambda conn, symbol, interval: None)
    onboarding.backfill(None, None, item, NOW)
    watermark = datetime(2026, 10, 24, 23, tzinfo=UTC)
    monkeypatch.setattr(onboarding, "get_watermark", lambda conn, symbol, interval: watermark)
    onboarding.backfill(None, None, item, NOW)

    assert windows == [datetime(2025, 10, 25, tzinfo=UTC), watermark - timedelta(days=1)]


def test_load_marks_unsupported_and_backfilling(monkeypatch) -> None:
    monkeypatch.setattr(
        onboarding,
        "claim",
        lambda client, now: [
            Claimed("NOPEUSDT", date(2025, 1, 1)),
            Claimed("LINKUSDT", date(2025, 1, 1)),
        ],
    )
    monkeypatch.setattr(
        onboarding,
        "backfill",
        lambda binance, conn, item, now: SyncResult(item.symbol, now, now, 1, 8760, 8760, 0),
    )
    warehouse = FakeWarehouse()

    loaded = load_claimed(FakeBinance({"LINKUSDT": pair("LINKUSDT", "LINK")}), warehouse, None, NOW)

    assert loaded == ["LINKUSDT"]
    statuses = [
        (p["symbol"], p["status"]) for _, p in warehouse.statements("SET status = %(status)s")
    ]
    assert statuses == [("NOPEUSDT", "unsupported"), ("LINKUSDT", "backfilling")]


def test_an_asset_is_ready_only_once_mart_has_its_rows() -> None:
    # DYN-06
    warehouse = FakeWarehouse(
        {
            "LEFT JOIN FINSIGHT.MART.MART_ASSET_DAILY": [
                {"SYMBOL": "LINKUSDT", "DATA_THROUGH": date(2026, 10, 24)},
                {"SYMBOL": "ARBUSDT", "DATA_THROUGH": None},
            ],
            "SELECT attempts": [{"ATTEMPTS": 0}],
        }
    )

    assert finalize(warehouse, NOW) == {"LINKUSDT": "ready", "ARBUSDT": "requested"}
