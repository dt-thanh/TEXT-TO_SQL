"""Turn paged Binance kline rows into typed, closed candles for one symbol and time window."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from src.common.exceptions import SourceAPIError
from src.ingestion.binance.client import MAX_KLINES_PER_REQUEST

logger = logging.getLogger(__name__)

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class KlineSource(Protocol):
    """Anything that serves raw kline rows: BinanceClient in production, fakes in tests."""

    def get_klines(
        self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int
    ) -> list[list[Any]]: ...


@dataclass(frozen=True)
class Kline:
    """One closed candle; the source columns of RAW.RAW_BINANCE_KLINE."""

    symbol: str
    interval_code: str
    open_time: datetime
    close_time: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    base_volume: Decimal
    quote_volume: Decimal
    trade_count: int
    taker_buy_base_volume: Decimal
    taker_buy_quote_volume: Decimal


def ms_to_utc(ms: int) -> datetime:
    """Convert Binance epoch milliseconds to an aware UTC datetime, without float rounding."""

    return EPOCH + timedelta(milliseconds=ms)


def to_ms(moment: datetime) -> int:
    """Convert an aware datetime to epoch milliseconds. Naive datetimes are ambiguous."""

    if moment.tzinfo is None:
        raise ValueError(f"{moment} has no timezone; pass an aware UTC datetime")
    return (moment - EPOCH) // timedelta(milliseconds=1)


def parse_kline(symbol: str, interval: str, row: list[Any]) -> Kline:
    """Map one positional Binance row to a Kline.

    Positions (Binance docs): 0 open time, 1 open, 2 high, 3 low, 4 close, 5 base volume,
    6 close time, 7 quote volume, 8 trade count, 9 taker buy base, 10 taker buy quote.
    Prices stay Decimal: floats cannot represent most decimal prices exactly.
    """

    try:
        return Kline(
            symbol=symbol,
            interval_code=interval,
            open_time=ms_to_utc(int(row[0])),
            close_time=ms_to_utc(int(row[6])),
            open_price=Decimal(row[1]),
            high_price=Decimal(row[2]),
            low_price=Decimal(row[3]),
            close_price=Decimal(row[4]),
            base_volume=Decimal(row[5]),
            quote_volume=Decimal(row[7]),
            trade_count=int(row[8]),
            taker_buy_base_volume=Decimal(row[9]),
            taker_buy_quote_volume=Decimal(row[10]),
        )
    except (IndexError, TypeError, ValueError, ArithmeticError) as err:
        raise SourceAPIError(f"Unexpected Binance kline row for {symbol}: {row!r}") from err


def extract_klines(
    source: KlineSource,
    symbol: str,
    interval: str,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
    page_size: int = MAX_KLINES_PER_REQUEST,
) -> list[Kline]:
    """Return every closed candle with start <= open_time < end, oldest first.

    Binance's endTime is inclusive, so we ask for end - 1 ms. The window is therefore
    half-open, and back-to-back windows never overlap or leave a gap.
    Candles still in progress at `now` are dropped: their numbers would change later.
    """

    start_ms, end_ms = to_ms(start), to_ms(end)
    now = now or datetime.now(UTC)
    klines: list[Kline] = []

    cursor = start_ms
    while cursor < end_ms:
        rows = source.get_klines(symbol, interval, cursor, end_ms - 1, page_size)
        if not rows:
            break
        klines.extend(parse_kline(symbol, interval, row) for row in rows)
        next_cursor = int(rows[-1][0]) + 1
        if next_cursor <= cursor:
            raise SourceAPIError(f"Binance pagination for {symbol} stopped advancing at {cursor}")
        cursor = next_cursor
        if len(rows) < page_size:
            break

    closed = [kline for kline in klines if kline.close_time < now]
    logger.info(
        "Extracted %d closed %s %s candles in [%s, %s), dropped %d still open",
        len(closed),
        symbol,
        interval,
        start.isoformat(),
        end.isoformat(),
        len(klines) - len(closed),
    )
    return closed
