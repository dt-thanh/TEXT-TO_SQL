-- Freshness of the result, not only of RAW: returns every asset whose newest day in the mart is
-- older than the day before yesterday (UTC). The mart excludes the unfinished current day, so
-- right after the 00:30 UTC run the newest day is yesterday; one extra day of slack lets a
-- manual `dbt build` before that run pass. A row here means users would get stale answers.

select
    symbol,
    max(trade_date) as newest_trade_date
from {{ ref('mart_asset_daily') }}
group by symbol
having max(trade_date) < dateadd(day, -2, current_date())
