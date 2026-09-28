-- Crypto daily performance next to the macro backdrop known that day (spec §11.3).
-- Grain: trade_date + symbol. The main table the Text-to-SQL agent will query.
--
-- mart_macro_daily has exactly one row per day, so this LEFT JOIN cannot multiply rows
-- (a test in _marts.yml checks the row count equals mart_asset_daily).

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
    macro.treasury_10y_source_date

from {{ ref('mart_asset_daily') }} as assets
left join {{ ref('mart_macro_daily') }} as macro
    on macro.market_date = assets.trade_date
