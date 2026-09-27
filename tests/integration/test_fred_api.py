"""Integration tests against the real FRED API: checks our reading of its vintage rules."""

from datetime import date
from decimal import Decimal

import pytest

from src.common.config import get_settings
from src.ingestion.fred.client import FredClient
from src.ingestion.fred.extractor import OPEN_END, extract_changes

pytestmark = pytest.mark.skipif(
    not get_settings().fred_api_key.get_secret_value(), reason="FRED_API_KEY is not set in .env"
)


def test_a_friday_yield_is_published_the_next_monday() -> None:
    with FredClient() as fred:
        changes = extract_changes(
            fred, "DGS10", date(2024, 12, 18), date(2024, 12, 18), date(2024, 12, 31)
        )

    by_date = {c.observation_date: c for c in changes}
    friday = by_date[date(2024, 12, 20)]
    assert (friday.realtime_start, friday.value) == (date(2024, 12, 23), Decimal("4.52"))
    christmas = by_date[date(2024, 12, 25)]
    assert (christmas.value_raw, christmas.value) == (".", None)


def test_revised_cpi_keeps_every_published_value() -> None:
    with FredClient() as fred:
        changes = extract_changes(fred, "CPIAUCSL", date(2024, 8, 1), date(2024, 9, 1), OPEN_END)

    august = [c for c in changes if c.observation_date == date(2024, 8, 1)]
    assert [(c.realtime_start, c.value) for c in august] == [
        (date(2024, 9, 11), Decimal("314.121")),
        (date(2025, 2, 12), Decimal("314.131")),
        (date(2026, 2, 13), Decimal("314.062")),
    ]
