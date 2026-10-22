"""Ask FinSight a research question from the terminal and print the Markdown report.

Run from the repository root:
    python -m scripts.research "Tương quan lợi nhuận BTC và ETH năm 2025?"
    make research Q="How did ETH volatility differ on days Ethereum TVL had fallen 10% in a week?"
    python -m scripts.research --out report.md "..."   # also save the report
Every number in the report comes from a verified SQL template shown under Evidence.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.agents.research.report import to_markdown
from src.agents.research.workflow import answer_research
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Research question → evidence-based report.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--out", type=Path, help="also write the Markdown report to this file")
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip()
    if not question:
        parser.error("the question is empty")

    setup_logging(get_settings().log_level)
    try:
        answer = answer_research(question)
    except FinSightError as err:
        logger.error("Could not answer: %s", err)
        return 1

    report = to_markdown(answer)
    print(report)
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
