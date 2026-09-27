-- Binance 1h candles, cleaned for everything downstream to read.
-- Grain: symbol + interval_code + open_time (same as RAW; tested in _staging.yml).
-- Cleaning only: explicit UTC, a trade_date, and a flag for candles cut short by exchange halts.
-- No returns or volatility here: business metrics belong to MART (spec §9).

with source as (

    select * from {{ source('raw', 'raw_binance_kline') }}

),

cleaned as (

    select
        symbol,
        interval_code,

        convert_timezone('UTC', open_time)        as open_time,
        convert_timezone('UTC', close_time)       as close_time,
        convert_timezone('UTC', open_time)::date  as trade_date,

        open_price,
        high_price,
        low_price,
        close_price,

        base_volume,
        quote_volume,
        trade_count,
        taker_buy_base_volume,
        taker_buy_quote_volume,

        -- A normal 1h candle closes at open + 59m 59.999s. About 30 candles since 2019 closed
        -- early because Binance halted trading; they stay, but are flagged.
        close_time = dateadd('millisecond', 3599999, open_time) as is_full_candle,

        ingested_at                               as loaded_at,
        batch_id

    from source

)

select * from cleaned
