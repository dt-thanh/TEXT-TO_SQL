{#-
    Hourly candles, the reusable crypto fact every mart builds on (spec §10.1).
    Grain: symbol + interval_code + open_time.

    Incremental: the first run builds the whole table; later runs only MERGE rows the loader
    inserted or changed since the previous dbt run. It is the loader's watermark + MERGE,
    written in SQL: {{ this }} is this table, and loaded_at is its watermark.
-#}
{{
    config(
        materialized='incremental',
        unique_key=['symbol', 'interval_code', 'open_time'],
        incremental_strategy='merge',
        on_schema_change='fail'
    )
}}

select
    symbol,
    interval_code,
    open_time,
    close_time,
    trade_date,

    open_price,
    high_price,
    low_price,
    close_price,

    base_volume,
    quote_volume,
    trade_count,
    taker_buy_base_volume,
    taker_buy_quote_volume,

    is_full_candle,
    loaded_at

from {{ ref('stg_binance_kline') }}

{% if is_incremental() %}
-- The loader stamps ingested_at (loaded_at here) on every row it inserts or changes, so this
-- picks up both new candles and corrections. The stamp is taken when a batch STARTS, not when
-- it commits, so with two loaders running at once a batch stamped earlier can commit after
-- dbt has already moved past it. Three hours of overlap covers that (a batch takes seconds);
-- the MERGE on unique_key makes re-processing those rows harmless.
where loaded_at > (select dateadd('hour', -3, max(loaded_at)) from {{ this }})
{% endif %}
