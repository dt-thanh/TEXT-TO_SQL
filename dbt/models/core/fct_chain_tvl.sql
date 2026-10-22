-- Every version of every chain's daily TVL, with the period it was the latest known value.
-- Grain: chain + tvl_date + fetched_date.
--
-- A full rebuild, like fct_macro_observation: a new version changes the valid_to of the old one.
-- About 13,000 rows.

select
    chain,
    tvl_date,
    fetched_date,
    valid_to,
    tvl_usd,
    is_backfill,
    loaded_at
from {{ ref('stg_defillama_chain_tvl') }}
