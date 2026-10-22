"""Turn DefiLlama TVL points into typed, finished days.

Two source quirks, checked on the live API (2026-10-22):
- the newest point is dated TODAY and keeps changing during the day, like an open candle, so
  only days that have ended are kept;
- the history starts with TVL = 0 before DefiLlama tracked the chain (Ethereum: 2017-09-27 to
  2018-02-11). That 0 means "no data yet", not "nothing locked", so it is dropped. Later gaps
  stay gaps: nothing is ever filled with 0.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from src.common.exceptions import SourceAPIError


class ChainTvlSource(Protocol):
    """Anything that serves raw TVL points: DefiLlamaClient in production, fakes in tests."""

    def get_chain_tvl(self, chain: str) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ChainTvl:
    """TVL of one chain at the start of one UTC day, in USD."""

    chain: str
    tvl_date: date
    tvl_usd: Decimal


def parse_point(chain: str, row: dict[str, Any]) -> ChainTvl:
    try:
        moment = datetime.fromtimestamp(int(row["date"]), tz=UTC)
        tvl = Decimal(str(row["tvl"]))
    except (KeyError, TypeError, ValueError, InvalidOperation, OverflowError) as err:
        raise SourceAPIError(f"Unexpected DefiLlama point for {chain}: {row!r}") from err
    if (moment.hour, moment.minute, moment.second) != (0, 0, 0):
        raise SourceAPIError(f"DefiLlama point for {chain} is not at 00:00 UTC: {row!r}")
    if not tvl.is_finite() or tvl < 0:
        raise SourceAPIError(f"DefiLlama TVL for {chain} is not a positive number: {row!r}")
    return ChainTvl(chain=chain, tvl_date=moment.date(), tvl_usd=tvl)


def parse_series(chain: str, rows: list[dict[str, Any]], today: date) -> list[ChainTvl]:
    """Finished days (tvl_date < today) from the first day with TVL > 0, oldest first."""

    points = sorted((parse_point(chain, row) for row in rows), key=lambda p: p.tvl_date)
    days = [p.tvl_date for p in points]
    if len(days) != len(set(days)):
        raise SourceAPIError(f"DefiLlama returned the same day twice for {chain}")
    first_tracked = next((i for i, p in enumerate(points) if p.tvl_usd > 0), len(points))
    return [p for p in points[first_tracked:] if p.tvl_date < today]


def extract_chain_tvl(source: ChainTvlSource, chain: str, today: date) -> list[ChainTvl]:
    return parse_series(chain, source.get_chain_tvl(chain), today)
