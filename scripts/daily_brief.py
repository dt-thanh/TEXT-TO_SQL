"""Make the daily brief of every watchlist and save it in CONTROL.DAILY_BRIEF.

Run by Airflow after the marts are built (finsight_daily, task generate_daily_brief), or by hand:
    python -m scripts.daily_brief                       # every watchlist, 30 days, saved
    python -m scripts.daily_brief --watchlist default --window 90
    python -m scripts.daily_brief --no-llm --print      # tables and evidence only, $0

One brief per watchlist and UTC day: a re-run replaces it. After Airflow was down for days it
still makes one brief, for the newest data, not one per missed day. When the daily LLM budget is
spent, the brief is made without the LLM (status partial) instead of being skipped.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime

from src.agents.research.brief import MAX_COST_USD, brief_to_dict, generate_brief
from src.agents.text_to_sql import agent_warehouse
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging
from src.control.briefs import save_brief
from src.control.usage import BudgetExceeded, CostCap
from src.control.watchlists import all_watchlists, check_name
from src.services.snowflake_client import SnowflakeClient

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make and save the daily briefs.")
    parser.add_argument("--watchlist", help="Only this watchlist (default: all of them)")
    parser.add_argument("--window", type=int, default=30, help="Days in the period (7-365)")
    parser.add_argument("--no-llm", action="store_true", help="Tables and evidence only, no cost")
    parser.add_argument("--print", action="store_true", help="Also print the Markdown")
    parser.add_argument("--language", choices=["en", "vi"], help="Default: BRIEF_LANGUAGE")
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level)
    language = args.language or settings.brief_language
    control = SnowflakeClient(query_tag="finsight-brief", keep_connection=True)
    warehouse = agent_warehouse()
    cap = CostCap(control, settings.llm_daily_cost_cap_usd)
    failures = 0
    try:
        lists = all_watchlists(control)
        if args.watchlist:
            name = check_name(args.watchlist)
            lists = {name: lists[name]} if name in lists else {}
            if not lists:
                logger.error("No watchlist named %s", name)
                return 1
        for name, symbols in lists.items():
            try:
                use_llm = not args.no_llm
                if use_llm:
                    try:
                        with cap.reserve(MAX_COST_USD) as record:
                            brief = generate_brief(symbols, args.window, name, language, True,
                                                   warehouse=warehouse)  # fmt: skip
                            record(brief.research.usage.cost_usd)
                    except BudgetExceeded as err:
                        logger.warning("%s: %s; making the brief without the LLM", name, err)
                        use_llm = False
                if not use_llm:
                    brief = generate_brief(symbols, args.window, name, language, False,
                                           warehouse=warehouse)  # fmt: skip
                now = datetime.now(UTC)
                save_brief(
                    control, now.date(), name, args.window, brief.status, brief.markdown,
                    brief_to_dict(brief), brief.research.usage.cost_usd, brief.research.seconds,
                    brief.research.data_as_of, now,
                )  # fmt: skip
                logger.info("Brief %s saved: %s", name, brief.status)
                if args.print:
                    print(brief.markdown)
            except FinSightError as err:
                failures += 1
                logger.error("Brief %s failed: %s", name, err)
    except FinSightError as err:
        logger.error("Daily brief failed: %s", err)
        return 1
    finally:
        control.close()
        warehouse.close()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
