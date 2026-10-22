-- Crypto daily performance next to the macro and DeFi backdrop known that day (spec §11.3).
-- Grain: trade_date + symbol. The main table the Text-to-SQL agent will query.
--
-- Every joined table has at most one row per day (per chain), so the LEFT JOINs cannot multiply
-- rows (a test in _marts.yml checks the row count equals mart_asset_daily).
-- TVL of day D is DefiLlama's 00:00 UTC point, known before day D's close: no look-ahead.

select
    assets.trade_date,
    assets.symbol,

    assets.close_price,
    assets.daily_return,
    assets.log_return,
    assets.volatility_30d,
    assets.base_volume,
    assets.quote_volume,

    macro.fed_funds_rate,
    macro.fed_rate_source_date,
    macro.treasury_10y,
    macro.treasury_10y_source_date,
    macro.treasury_10y_change_bps,

    chain_tvl.chain                  as chain,
    chain_tvl.tvl_usd                as chain_tvl_usd,
    chain_tvl.tvl_change_7d          as chain_tvl_change_7d,
    defi_tvl.tvl_usd                 as defi_tvl_usd,
    defi_tvl.tvl_change_7d           as defi_tvl_change_7d

from {{ ref('mart_asset_daily') }} as assets
left join {{ ref('mart_macro_daily') }} as macro
    on macro.market_date = assets.trade_date
left join {{ ref('dim_chain') }} as chains
    on chains.related_symbol = assets.symbol
left join {{ ref('mart_chain_tvl_daily') }} as chain_tvl
    on  chain_tvl.chain = chains.chain_slug
    and chain_tvl.tvl_date = assets.trade_date
left join {{ ref('mart_chain_tvl_daily') }} as defi_tvl
    on  defi_tvl.chain = 'All'
    and defi_tvl.tvl_date = assets.trade_date
