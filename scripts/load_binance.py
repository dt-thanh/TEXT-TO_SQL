"""Load closed Binance candles into RAW.RAW_BINANCE_KLINE. Safe to re-run.

Run from the repository root:
    python -m scripts.load_binance                        # incremental: from each watermark to now
                                                          # (core assets + ready registry assets)
    python -m scripts.load_binance --start 2019-01-01     # explicit window: backfill or repair
    python -m scripts.load_binance --symbols BTCUSDT --start 2024-01-01 --end 2024-01-08
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from scripts.extract_binance import utc_date
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.control.assets import daily_symbols
from src.ingestion.binance.client import BinanceClient
from src.ingestion.binance.sync import MVP_SYMBOLS, load_window, sync_symbol
from src.services.snowflake_client import ConnectionRunner, SnowflakeClient

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load closed Binance candles into RAW.")
    parser.add_argument(
        "--symbols", nargs="+", help="Default: core assets + assets ready in CONTROL.ASSET_REGISTRY"
    )
    parser.add_argument("--interval", default="1h")
    parser.add_argument(
        "--start", type=utc_date, help="YYYY-MM-DD UTC, inclusive. Omit for an incremental run."
    )
    parser.add_argument("--end", type=utc_date, help="YYYY-MM-DD UTC, exclusive (default: now)")
    args = parser.parse_args(argv)
    if args.end and not args.start:
        parser.error("--end needs --start")

    setup_logging(get_settings().log_level)
    now = datetime.now(UTC)
    try:
        with BinanceClient() as binance, SnowflakeClient().connect() as conn:
            symbols = args.symbols or daily_symbols(ConnectionRunner(conn), MVP_SYMBOLS)
            logger.info("Symbols: %s", ", ".join(symbols))
            for symbol in symbols:
                if args.start:
                    end = args.end or now
                    load_window(binance, conn, symbol, args.interval, args.start, end, now)
                else:
                    sync_symbol(binance, conn, symbol, args.interval, now)
    except FinSightError as err:
        logger.error("Load failed: %s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
