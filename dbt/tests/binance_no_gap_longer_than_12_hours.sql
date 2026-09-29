-- Singular test: every row returned is a stretch of more than 12 hours with no candle.
--
-- Binance itself has short outages (about 60 missing hours since 2019, the longest 10 hours on
-- 2019-05-15), so short gaps are normal. A longer gap almost certainly means OUR pipeline missed
-- data, e.g. a backfill that was interrupted and never resumed.

with ordered as (

    select
        symbol,
        interval_code,
        open_time,
        lag(open_time) over (
            partition by symbol, interval_code
            order by open_time
        ) as previous_open_time
    from {{ ref('stg_binance_kline') }}

)

select
    symbol,
    interval_code,
    previous_open_time,
    open_time,
    datediff('hour', previous_open_time, open_time) - 1 as missing_hours
from ordered
where datediff('hour', previous_open_time, open_time) - 1 > 12
