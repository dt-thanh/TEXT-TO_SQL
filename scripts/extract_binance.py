"""Extract closed Binance candles for one symbol and log a summary. No database needed.

Run from the repository root, for example:
    python -m scripts.extract_binance --symbol BTCUSDT --start 2024-01-01 --end 2024-01-08
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.ingestion.binance.client import BinanceClient
from src.ingestion.binance.extractor import extract_klines

logger = logging.getLogger(__name__)


def utc_date(value: str) -> datetime:
    """Read YYYY-MM-DD as midnight UTC."""

    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract closed Binance candles.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", type=utc_date, required=True, help="YYYY-MM-DD UTC, inclusive")
    parser.add_argument("--end", type=utc_date, help="YYYY-MM-DD UTC, exclusive (default: now)")
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    end = args.end or datetime.now(UTC)
    try:
        with BinanceClient() as client:
            klines = extract_klines(client, args.symbol, args.interval, args.start, end)
    except FinSightError as err:
        logger.error("Extraction failed: %s", err)
        return 1

    for label, kline in (("first", klines[0]), ("last", klines[-1])) if klines else ():
        logger.info(
            "%-5s open_time=%s close=%s volume=%s trades=%d",
            label,
            kline.open_time.isoformat(),
            kline.close_price,
            kline.base_volume,
            kline.trade_count,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
