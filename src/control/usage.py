"""Daily LLM cost cap for the whole system (spec v1.1, 6.3).

All LLM calls of one UTC day together, API requests and scheduled briefs, stop at
LLM_DAILY_COST_CAP_USD. Before a request that may call the model, its maximum cost (the request's
own budget: research $0.01, brief $0.02) is reserved; afterwards the real cost is added to
CONTROL.API_USAGE. Reserving the maximum means parallel requests cannot pass the cap together.
Reservations live in this process (one API instance); the spend is in Snowflake, shared with the
Airflow brief job.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

from src.common.exceptions import FinSightError
from src.control.assets import CONTROL, Warehouse

logger = logging.getLogger(__name__)


class BudgetExceeded(FinSightError):
    def __init__(self, spent: float, cap: float) -> None:
        super().__init__(f"daily LLM budget reached: ${spent:.4f} of ${cap:.2f} spent today (UTC)")
        self.spent, self.cap = spent, cap


class CostCap:
    def __init__(
        self,
        client: Warehouse,
        cap_usd: float,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.client = client
        self.cap_usd = cap_usd
        self.clock = clock
        self._reserved = 0.0
        self._lock = threading.Lock()

    def today(self) -> date:
        return self.clock().date()

    def spent_today(self) -> float:
        rows = self.client.execute(
            f"SELECT llm_cost_usd FROM {CONTROL}.API_USAGE WHERE usage_date = %(day)s",
            {"day": self.today()},
        )
        return float(rows[0]["LLM_COST_USD"]) if rows else 0.0

    def status(self) -> dict[str, float]:
        spent = self.spent_today()
        return {
            "spent_usd": round(spent, 6),
            "reserved_usd": round(self._reserved, 6),
            "cap_usd": self.cap_usd,
            "remaining_usd": round(max(0.0, self.cap_usd - spent - self._reserved), 6),
        }

    @contextmanager
    def reserve(self, max_cost_usd: float) -> Iterator[Callable[[float], None]]:
        """Hold `max_cost_usd` of today's budget; yield a function that records the real cost.

        Raises BudgetExceeded before anything runs when the budget cannot cover the request.
        """

        with self._lock:
            spent = self.spent_today()
            if spent + self._reserved + max_cost_usd > self.cap_usd:
                raise BudgetExceeded(spent + self._reserved, self.cap_usd)
            self._reserved += max_cost_usd
        try:
            yield self.record
        finally:
            with self._lock:
                self._reserved -= max_cost_usd

    def record(self, cost_usd: float) -> None:
        if cost_usd <= 0:
            return
        self.client.execute(
            f"""
MERGE INTO {CONTROL}.API_USAGE AS t
USING (SELECT %(day)s::date AS usage_date) AS s ON t.usage_date = s.usage_date
WHEN MATCHED THEN UPDATE SET
    llm_cost_usd = t.llm_cost_usd + %(cost)s, llm_requests = t.llm_requests + 1,
    updated_at = %(now)s
WHEN NOT MATCHED THEN INSERT (usage_date, llm_cost_usd, llm_requests, updated_at)
VALUES (%(day)s, %(cost)s, 1, %(now)s)
""",
            {"day": self.today(), "cost": float(cost_usd), "now": self.clock()},
        )
        logger.info("LLM cost recorded: $%.5f", cost_usd)
