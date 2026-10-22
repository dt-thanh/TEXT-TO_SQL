-- DefiLlama TVL versions, with the validity period of each version filled in.
-- Grain: chain + tvl_date + fetched_date (tested in _staging.yml).
-- RAW keeps a new row only when a fetch saw a new or changed value. A version stays the latest
-- known value of its day until the day before the next version; the current one is open-ended
-- (9999-12-31), the same convention as stg_fred_observation.

with source as (

    select * from {{ source('raw', 'raw_defillama_chain_tvl') }}

)

select
    chain,
    tvl_date,

    fetched_date,
    coalesce(
        dateadd(
            'day',
            -1,
            lead(fetched_date) over (partition by chain, tvl_date order by fetched_date)
        ),
        '9999-12-31'::date
    )                     as valid_to,

    tvl_usd,
    is_backfill,

    ingested_at           as loaded_at,
    batch_id

from source
