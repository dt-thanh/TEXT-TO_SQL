"""Load FRED series metadata and observation vintages into RAW. Safe to re-run.

Run from the repository root:
    python -m scripts.load_fred                      # incremental: since each watermark
    python -m scripts.load_fred --start 2018-12-01   # explicit: every publication from that day on
    python -m scripts.load_fred --series DGS10 --start 2024-01-01
"""

import argparse
import logging
import sys
from datetime import UTC, date, datetime

from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.ingestion.fred.client import FredClient
from src.ingestion.fred.sync import MVP_SERIES, load_vintages, sync_series
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load FRED observation vintages into RAW.")
    parser.add_argument("--series", nargs="+", default=list(MVP_SERIES))
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        help="YYYY-MM-DD: load everything FRED published from this day on. Omit for incremental.",
    )
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    today = datetime.now(UTC).date()
    try:
        with FredClient() as fred, SnowflakeClient().connect() as conn:
            for series_id in args.series:
                if args.start:
                    load_vintages(fred, conn, series_id, args.start, today)
                else:
                    sync_series(fred, conn, series_id, today)
    except FinSightError as err:
        logger.error("Load failed: %s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
