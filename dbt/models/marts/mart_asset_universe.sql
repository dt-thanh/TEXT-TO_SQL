-- One row per asset FinSight knows (spec v1.1, 3.7): the one list the agent, the research
-- resolver and the UI share. An asset is `ready` when MART has daily rows for it and it is not
-- disabled, so readiness never depends on when this table was last rebuilt relative to the
-- registry. TVL comes only from the curated chain mapping (dim_chain), never from a ticker.

with coverage as (
    select
        symbol,
        min(trade_date) as data_from,
        max(trade_date) as data_through,
        count(*)        as n_days
    from {{ ref('mart_asset_daily') }}
    group by symbol
)

select
    a.symbol,
    a.asset_key,
    a.base_asset,
    a.asset_name as display_name,
    a.is_core,
    c.chain_slug,
    cov.data_from,
    cov.data_through,
    coalesce(cov.n_days, 0) as n_days,
    case
        when not a.is_active then 'disabled'
        when cov.data_through is not null then 'ready'
        else 'loading'
    end as status
from {{ ref('dim_asset') }} as a
left join coverage as cov on cov.symbol = a.symbol
left join {{ ref('dim_chain') }} as c on c.related_symbol = a.symbol
