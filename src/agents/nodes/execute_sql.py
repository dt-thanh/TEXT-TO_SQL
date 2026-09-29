"""Run the guard's rewrite as the read-only agent user and classify a failure."""

import logging
import time
from typing import Any

from src.agents.state import AgentState, Attempt
from src.common.exceptions import WarehouseError

logger = logging.getLogger(__name__)


def is_fixable_by_rewriting(error: str) -> bool:
    """Compilation errors (unknown column, syntax, wrong argument types) are mistakes in the SQL
    text, so a rewrite can fix them. A timeout, a lost connection or a missing privilege cannot."""

    return "SQL compilation error" in error


def execute_sql(state: AgentState, *, warehouse: Any, max_rows: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        # The guard's LIMIT caps the rows in Snowflake; max_rows here is a second cap on fetching.
        rows = warehouse.execute(state["safe_sql"], max_rows=max_rows)
    except WarehouseError as err:
        error = str(err)
        logger.warning("SQL failed: %s", error)
        return {
            "error": error,
            "retryable": is_fixable_by_rewriting(error),
            # The SQL that ran, so the error's line numbers point at the right lines.
            "attempts": [Attempt(sql=state["safe_sql"], error=error)],
            "sql_seconds": time.perf_counter() - started,
        }
    seconds = time.perf_counter() - started
    logger.info("SQL returned %d row(s) in %.1fs", len(rows), seconds)
    return {"rows": rows, "error": None, "sql_seconds": seconds}
