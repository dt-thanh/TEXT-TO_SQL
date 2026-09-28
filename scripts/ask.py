"""Ask FinSight a question in plain language from the terminal.

Run from the repository root:
    python -m scripts.ask "BTC biến động thế nào khi lợi suất 10 năm trên 4%?"
    make ask Q="Which asset had the highest 30-day volatility yesterday?"
Prints the SQL, how it works, the result table, and what the LLM call cost.
"""

import logging
import sys

from src.agents.text_to_sql import answer_question
from src.common.config import get_settings
from src.common.exceptions import FinSightError
from src.common.logging_config import setup_logging

logger = logging.getLogger(__name__)
SHOWN_ROWS = 20


def format_table(rows: list[dict[str, object]], limit: int = SHOWN_ROWS) -> str:
    """Plain-text table of the first `limit` rows."""

    if not rows:
        return "(no rows)"
    columns = list(rows[0])
    shown = [[str(row[c]) for c in columns] for row in rows[:limit]]
    widths = [max(len(c), *(len(r[i]) for r in shown)) for i, c in enumerate(columns)]
    lines = [" | ".join(c.ljust(w) for c, w in zip(columns, widths, strict=True))]
    lines.append("-+-".join("-" * w for w in widths))
    lines += [" | ".join(v.ljust(w) for v, w in zip(r, widths, strict=True)) for r in shown]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or not " ".join(args).strip():
        print('Usage: python -m scripts.ask "your question"')
        return 2
    question = " ".join(args).strip()

    setup_logging(get_settings().log_level)
    try:
        answer = answer_question(question)
    except FinSightError as err:
        logger.error("Could not answer: %s", err)
        return 1

    print(f"\nQUESTION\n{answer.question}\n")
    print(f"GENERATED SQL\n{answer.sql or '(none)'}\n")
    print(f"HOW THIS SQL WORKS\n{answer.explanation}\n")
    if answer.error:
        print(f"ERROR\n{answer.error}\n")
    print("RESULT")
    print(format_table(answer.rows))
    if answer.truncated or len(answer.rows) > SHOWN_ROWS:
        print(f"... showing {min(SHOWN_ROWS, len(answer.rows))} rows")
    u = answer.usage
    print(
        f"\nCOST  {u.input_tokens} input + {u.output_tokens} output tokens = ${u.cost_usd:.5f}"
        f"  |  LLM {answer.llm_seconds:.1f}s, SQL {answer.sql_seconds:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
