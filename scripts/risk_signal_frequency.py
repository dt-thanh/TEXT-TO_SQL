"""How often each risk rule fires on real data (spec v1.1, 4.6 / RISK-05).

Share of eligible days (days with enough history for the rule) on which the rule fired, per rule
and asset. A rule that fires on many days is noise for an event signal, or a state signal that
lasts (a drawdown). Prints a Markdown table for docs/risk_signals.md. No LLM, a few queries.
    python -m scripts.risk_signal_frequency
"""

import sys

from src.services.snowflake_client import SnowflakeClient

SQL = """
with rules as (select * from FINSIGHT.STAGING.RISK_SIGNAL_RULES),
eligible as (
    -- Days on which the rule had its full window behind it.
    select a.symbol, r.signal_id, count(*) as eligible_days
    from FINSIGHT.MART.MART_ASSET_DAILY as a
    join (select symbol, min(trade_date) as first_day from FINSIGHT.MART.MART_ASSET_DAILY
          group by symbol) as f on f.symbol = a.symbol
    join rules as r on r.signal_id in ('abnormal_move', 'volatility_spike', 'drawdown_alert')
    where a.trade_date >= dateadd('day', r.window_days + 30, f.first_day)
    group by a.symbol, r.signal_id
    union all
    select t.related_symbol, 'tvl_drop', count(*) - 30
    from FINSIGHT.MART.MART_CHAIN_TVL_DAILY as t
    where t.related_symbol is not null
    group by t.related_symbol
),
fired as (
    select symbol, signal_id, count(*) as fired_days, max(trade_date) as last_fired
    from FINSIGHT.MART.MART_RISK_SIGNAL_DAILY
    group by symbol, signal_id
)
select e.signal_id, e.symbol, e.eligible_days, coalesce(f.fired_days, 0) as fired_days,
       coalesce(f.fired_days, 0) / nullif(e.eligible_days, 0) as share, f.last_fired
from eligible as e
left join fired as f on f.symbol = e.symbol and f.signal_id = e.signal_id
order by e.signal_id, e.symbol
"""


def main() -> int:
    rows = SnowflakeClient().execute(SQL)
    print("| Rule | Asset | Eligible days | Days fired | Share | Last fired |")
    print("|---|---|---:|---:|---:|---|")
    for row in rows:
        share = float(row["SHARE"] or 0)
        print(
            f"| {row['SIGNAL_ID']} | {row['SYMBOL']} | {row['ELIGIBLE_DAYS']} | "
            f"{row['FIRED_DAYS']} | {share:.1%} | {row['LAST_FIRED'] or '—'} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
