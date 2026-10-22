-- Known-answer test: values checked by hand against the source APIs must come out of the marts
-- unchanged. Returns one row per check that is wrong OR missing (a missing row must not pass).
--
--   BTC daily close 2024-01-01 = close of the 23:00 UTC candle: 44179.55
--   DGS10 known on Sun 2024-12-22 = Thu 12-19 value 4.57, published Fri 12-20
--   DGS10 known on Mon 2024-12-23 = Fri 12-20 value 4.52, published that Monday
-- The last two are the point-in-time rule: Friday's yield is not known until Monday.
--   Ethereum DeFi TVL 2024-01-01 = 28,456,740,243 USD, 7-day change -0.008053
--     (DefiLlama /v2/historicalChainTvl/Ethereum, read 2026-10-22; 2023-12-25 = 28,687,760,248)
--   ETHUSDT row of 2024-01-01 carries that same chain TVL (the asset-to-chain join)

with expected as (

    select check_name, expected_value
    from (
        values
            ('BTCUSDT daily close 2024-01-01', 44179.55),
            ('DGS10 known on 2024-12-22',      4.57),
            ('DGS10 known on 2024-12-23',      4.52),
            ('Ethereum TVL 2024-01-01',        28456740243),
            ('Ethereum TVL 7d change 2024-01-01', -0.008053),
            ('ETHUSDT chain TVL 2024-01-01',   28456740243)
    ) as t (check_name, expected_value)

),

actual as (

    select 'BTCUSDT daily close 2024-01-01' as check_name, close_price as actual_value
    from {{ ref('mart_asset_daily') }}
    where symbol = 'BTCUSDT' and trade_date = '2024-01-01'

    union all

    select 'DGS10 known on 2024-12-22', treasury_10y
    from {{ ref('mart_macro_daily') }}
    where market_date = '2024-12-22'

    union all

    select 'DGS10 known on 2024-12-23', treasury_10y
    from {{ ref('mart_macro_daily') }}
    where market_date = '2024-12-23'

    union all

    select 'Ethereum TVL 2024-01-01', tvl_usd
    from {{ ref('mart_chain_tvl_daily') }}
    where chain = 'Ethereum' and tvl_date = '2024-01-01'

    union all

    select 'Ethereum TVL 7d change 2024-01-01', round(tvl_change_7d, 6)
    from {{ ref('mart_chain_tvl_daily') }}
    where chain = 'Ethereum' and tvl_date = '2024-01-01'

    union all

    select 'ETHUSDT chain TVL 2024-01-01', chain_tvl_usd
    from {{ ref('mart_market_macro_daily') }}
    where symbol = 'ETHUSDT' and trade_date = '2024-01-01'

)

select
    expected.check_name,
    expected.expected_value,
    actual.actual_value
from expected
left join actual
    on actual.check_name = expected.check_name
where actual.actual_value is null
   or actual.actual_value <> expected.expected_value
