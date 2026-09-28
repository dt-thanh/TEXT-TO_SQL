-- One row per tracked asset (spec §10.4). Built from the binance_assets seed, the single place
-- that defines the asset universe; fct_crypto_kline_1h is tested against it (relationships).

select
    asset_id,
    symbol,
    base_asset,
    quote_asset,
    asset_name,
    asset_type,
    exchange,
    is_active
from {{ ref('binance_assets') }}
