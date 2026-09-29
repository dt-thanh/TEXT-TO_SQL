-- One row per asset per UTC day: daily prices, volume and the MVP risk metrics (spec §11.1).
-- Grain: trade_date + symbol. Only finished days: today's row appears tomorrow.
--
-- Metric definitions (spec §24; change them only together with _marts.yml and its tests):
--   daily_return   = close / previous day's close - 1
--   log_return     = ln(close / previous day's close)
--   volatility_30d = sample standard deviation of the last 30 daily log returns × sqrt(365),
--                    NULL until 30 returns exist. sqrt(365), not 252: crypto trades every day.

with hourly as (

    select * from {{ ref('fct_crypto_kline_1h') }}
    -- A day that has not ended has no daily close yet.
    where trade_date < current_date()

),

daily as (

    select
        trade_date,
        symbol,
        min_by(open_price, open_time)   as open_price,    -- open of the day's first candle
        max(high_price)                 as high_price,
        min(low_price)                  as low_price,
        max_by(close_price, open_time)  as close_price,   -- close of the day's last candle
        sum(base_volume)                as base_volume,
        sum(quote_volume)               as quote_volume,
        sum(trade_count)                as trade_count,
        -- Exchange outages leave some days with fewer than 24 hourly candles.
        count(*)                        as candle_count,
        count(*) = 24                   as is_complete_day
    from hourly
    group by trade_date, symbol

),

with_returns as (

    select
        daily.*,
        lag(close_price) over (partition by symbol order by trade_date) as previous_close,
        close_price / previous_close - 1                                  as daily_return,
        ln(close_price / previous_close)                                  as log_return
    from daily

)

select
    trade_date,
    symbol,

    open_price,
    high_price,
    low_price,
    close_price,

    base_volume,
    quote_volume,
    trade_count,
    candle_count,
    is_complete_day,

    daily_return,
    log_return,
    iff(
        count(log_return) over (
            partition by symbol order by trade_date rows between 29 preceding and current row
        ) = 30,
        stddev_samp(log_return) over (
            partition by symbol order by trade_date rows between 29 preceding and current row
        ) * sqrt(365),
        null
    )                                                                     as volatility_30d

from with_returns
