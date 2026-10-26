"""Saved daily briefs in CONTROL.DAILY_BRIEF: one per UTC day and watchlist, replaced on re-run."""

import json
from datetime import date
from typing import Any

from src.control.assets import CONTROL, Warehouse


def save_brief(
    client: Warehouse,
    brief_date: date,
    watchlist_name: str,
    window_days: int,
    status: str,
    markdown: str,
    response: dict[str, Any],
    cost_usd: float,
    seconds: float,
    data_as_of: date | None,
    now: Any,
) -> None:
    client.execute(
        f"""
MERGE INTO {CONTROL}.DAILY_BRIEF AS t
USING (SELECT %(day)s::date AS brief_date, %(name)s AS watchlist_name) AS s
    ON t.brief_date = s.brief_date AND t.watchlist_name = s.watchlist_name
WHEN MATCHED THEN UPDATE SET
    window_days = %(window)s, status = %(status)s, markdown = %(markdown)s,
    response_json = PARSE_JSON(%(response)s), cost_usd = %(cost)s, seconds = %(seconds)s,
    data_as_of = %(as_of)s, created_at = %(now)s
WHEN NOT MATCHED THEN INSERT
    (brief_date, watchlist_name, window_days, status, markdown, response_json, cost_usd, seconds,
     data_as_of, created_at)
VALUES
    (%(day)s, %(name)s, %(window)s, %(status)s, %(markdown)s, PARSE_JSON(%(response)s), %(cost)s,
     %(seconds)s, %(as_of)s, %(now)s)
""",
        {
            "day": brief_date,
            "name": watchlist_name,
            "window": window_days,
            "status": status,
            "markdown": markdown,
            "response": json.dumps(response, default=str),
            "cost": cost_usd,
            "seconds": seconds,
            "as_of": data_as_of,
            "now": now,
        },
    )


def list_briefs(client: Warehouse, watchlist_name: str | None, limit: int = 14) -> list[dict]:
    where = "WHERE watchlist_name = %(name)s" if watchlist_name else ""
    return client.execute(
        f"""
SELECT brief_date, watchlist_name, window_days, status, cost_usd, seconds, data_as_of, created_at
FROM {CONTROL}.DAILY_BRIEF {where}
ORDER BY brief_date DESC, watchlist_name
LIMIT {int(limit)}
""",
        {"name": watchlist_name},
    )


def get_brief(client: Warehouse, brief_date: date, watchlist_name: str) -> dict | None:
    rows = client.execute(
        f"""
SELECT brief_date, watchlist_name, window_days, status, markdown, cost_usd, seconds, data_as_of,
       created_at
FROM {CONTROL}.DAILY_BRIEF
WHERE brief_date = %(day)s AND watchlist_name = %(name)s
""",
        {"day": brief_date, "name": watchlist_name},
    )
    return rows[0] if rows else None
