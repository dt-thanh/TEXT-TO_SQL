"""Asset universe jobs: Binance catalog, onboarding steps, and adding an asset by hand.

Run from the repository root:
    python -m scripts.onboard_assets refresh-catalog   # daily: USDT spot pairs Binance trades
    python -m scripts.onboard_assets load              # onboarding step 1 (exit 99: nothing to do)
    python -m scripts.onboard_assets finalize          # onboarding step 3, after dbt
    python -m scripts.onboard_assets add link avax arbb  # check; add the right ones

Exit code 99 makes Airflow's BashOperator mark the task skipped, so dbt and finalize are skipped
too when no asset is waiting.
"""

import argparse
import logging
import sys

from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.control.airflow_trigger import trigger_dag
from src.control.assets import CONTROL, AssetError, check_symbols, request_asset, split_input
from src.control.onboarding import finalize, load_claimed, refresh_catalog
from src.ingestion.binance.client import BinanceClient
from src.services.snowflake_client import ConnectionRunner, SnowflakeClient

logger = logging.getLogger(__name__)

NOTHING_TO_DO = 99


def pending(runner: ConnectionRunner) -> int:
    rows = runner.execute(
        f"SELECT COUNT(*) AS n FROM {CONTROL}.ASSET_REGISTRY WHERE status = 'backfilling'"
    )
    return int(rows[0]["N"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FinSight asset universe jobs.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("refresh-catalog")
    commands.add_parser("load")
    commands.add_parser("finalize")
    add = commands.add_parser("add")
    add.add_argument("coins", nargs="+", help="e.g. link avax ARBUSDT (commas work too)")
    args = parser.parse_args(argv)

    setup_logging(get_settings().log_level)
    try:
        with SnowflakeClient(query_tag="finsight-onboarding").connect() as conn:
            runner = ConnectionRunner(conn)
            if args.command == "refresh-catalog":
                with BinanceClient() as binance:
                    refresh_catalog(binance, conn)
            elif args.command == "load":
                with BinanceClient() as binance:
                    load_claimed(binance, runner, conn)
                if pending(runner) == 0:
                    logger.info("No asset is waiting for onboarding")
                    return NOTHING_TO_DO
            elif args.command == "finalize":
                print(finalize(runner))
            else:
                requested = False
                for result in check_symbols(runner, split_input(" ".join(args.coins))):
                    if result["ok"] and result["action"] == "add":
                        try:  # a limit stops this coin only, never the others
                            status = request_asset(runner, result["symbol"])
                            requested = requested or status == "requested"
                            result["message"] = f"{status}: loading history"
                        except AssetError as err:
                            result.update(ok=False, message=str(err))
                    mark = "OK " if result["ok"] else "ERR"
                    hint = result.get("suggestions")
                    hint = f" — did you mean {', '.join(hint)}?" if hint else ""
                    print(f"{mark} {result['input']:>12} → {result['symbol'] or '-'}: "
                          f"{result['message']}{hint}")  # fmt: skip
                if requested:
                    trigger_dag()
    except FinSightError as err:
        logger.error("%s failed: %s", args.command, err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
