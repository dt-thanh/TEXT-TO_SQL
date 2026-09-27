"""Extract closed Binance candles for one symbol and window, then MERGE them into RAW.

Run from the repository root, for example:
    python -m scripts.load_binance --symbol BTCUSDT --start 2024-01-01 --end 2024-01-08
Running the same command twice must leave the table unchanged.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from scripts.extract_binance import utc_date
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.ingestion.binance.client import BinanceClient
from src.ingestion.binance.extractor import extract_klines
from src.ingestion.binance.loader import RAW_TABLE, load_klines, new_batch_id
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)

COUNT_SQL = f"""
SELECT COUNT(*) AS row_count
FROM {RAW_TABLE}
WHERE symbol = %(symbol)s AND interval_code = %(interval)s
  AND open_time >= %(start)s AND open_time < %(end)s
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load closed Binance candles into RAW.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--start", type=utc_date, required=True, help="YYYY-MM-DD UTC, inclusive")
    parser.add_argument("--end", type=utc_date, help="YYYY-MM-DD UTC, exclusive (default: now)")
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    end = args.end or datetime.now(UTC)
    window = {"symbol": args.symbol, "interval": args.interval, "start": args.start, "end": end}
    try:
        with BinanceClient() as binance:
            klines = extract_klines(binance, args.symbol, args.interval, args.start, end)
        with SnowflakeClient().connect() as conn:
            load_klines(conn, klines, new_batch_id())
            with conn.cursor() as cur:
                row_count = cur.execute(COUNT_SQL, window).fetchone()[0]
    except FinSightError as err:
        logger.error("Load failed: %s", err)
        return 1

    logger.info(
        "%s now holds %d %s %s rows in [%s, %s)",
        RAW_TABLE,
        row_count,
        args.symbol,
        args.interval,
        args.start.isoformat(),
        end.isoformat(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
