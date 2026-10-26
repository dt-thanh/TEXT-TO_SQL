-- One row per asset FinSight knows (spec v1.1, 3.7): the four core assets from the binance_assets
-- seed (history since 2019) plus every asset the owner added through CONTROL.ASSET_REGISTRY that
-- may have candles in RAW. fct_crypto_kline_1h is tested against this table (relationships), so
-- an asset being backfilled must already be here; whether it is ready is decided in MART
-- (mart_asset_universe: it has daily rows).

with core as (
    select
        asset_id,
        symbol,
        base_asset,
        quote_asset,
        asset_name,
        asset_type,
        exchange,
        is_active,
        true as is_core,
        'core' as registry_status
    from {{ ref('binance_assets') }}
),

added as (
    select
        r.base_asset as asset_id,
        r.symbol,
        r.base_asset,
        r.quote_asset,
        coalesce(r.display_name, r.base_asset) as asset_name,
        'CRYPTO' as asset_type,
        'BINANCE' as exchange,
        r.status <> 'disabled' as is_active,
        false as is_core,
        r.status as registry_status
    from {{ source('control', 'asset_registry') }} as r
    -- A pair Binance does not trade never had candles loaded.
    where r.status <> 'unsupported'
      and r.symbol not in (select symbol from core)
)

select
    *,
    exchange || ':' || base_asset as asset_key
from (
    select * from core
    union all
    select * from added
)
