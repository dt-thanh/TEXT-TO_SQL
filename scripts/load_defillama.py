"""Load DefiLlama daily TVL per chain into RAW. Safe to re-run.

Run from the repository root:
    python -m scripts.load_defillama                     # every MVP chain
    python -m scripts.load_defillama --chains Ethereum
The first run of a chain loads its whole history (a backfill); later runs add new days and keep
a new version of any past day DefiLlama has revised.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.ingestion.defillama.client import DefiLlamaClient
from src.ingestion.defillama.sync import MVP_CHAINS, sync_chain
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load DefiLlama chain TVL into RAW.")
    parser.add_argument("--chains", nargs="+", default=list(MVP_CHAINS))
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    today = datetime.now(UTC).date()
    try:
        with DefiLlamaClient() as defillama, SnowflakeClient().connect() as conn:
            for chain in args.chains:
                sync_chain(defillama, conn, chain, today)
    except FinSightError as err:
        logger.error("Load failed: %s", err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
