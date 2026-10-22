-- One row per chain per UTC day: DefiLlama TVL and its 1-day and 7-day change.
-- Grain: tvl_date + chain.
--
-- tvl_usd is the newest version of the day (DefiLlama's current view of it). is_retrospective
-- marks values that were not yet available the day after tvl_date: the first, historical load
-- (backfill) or a later revision. Those describe the day as DefiLlama sees it now, not what an
-- analyst could have known then.
-- Changes compare CALENDAR days (tvl_date - 1, tvl_date - 7), never "the row 7 rows earlier":
-- a missing day gives NULL instead of a change over a longer, unstated period.

with latest as (

    select chain, tvl_date, tvl_usd, fetched_date
    from {{ ref('fct_chain_tvl') }}
    qualify row_number() over (partition by chain, tvl_date order by fetched_date desc) = 1

)

select
    today.tvl_date,
    today.chain,
    chains.related_symbol,

    today.tvl_usd,
    today.tvl_usd / day_before.tvl_usd - 1                   as tvl_change_1d,
    today.tvl_usd / week_before.tvl_usd - 1                  as tvl_change_7d,

    today.fetched_date,
    today.fetched_date > dateadd('day', 1, today.tvl_date)   as is_retrospective

from latest as today
join {{ ref('dim_chain') }} as chains
    on chains.chain_slug = today.chain
left join latest as day_before
    on  day_before.chain = today.chain
    and day_before.tvl_date = dateadd('day', -1, today.tvl_date)
left join latest as week_before
    on  week_before.chain = today.chain
    and week_before.tvl_date = dateadd('day', -7, today.tvl_date)
