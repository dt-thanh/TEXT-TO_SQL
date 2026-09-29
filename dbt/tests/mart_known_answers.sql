-- Known-answer test: values checked by hand against the source APIs must come out of the marts
-- unchanged. Returns one row per check that is wrong OR missing (a missing row must not pass).
--
--   BTC daily close 2024-01-01 = close of the 23:00 UTC candle: 44179.55
--   DGS10 known on Sun 2024-12-22 = Thu 12-19 value 4.57, published Fri 12-20
--   DGS10 known on Mon 2024-12-23 = Fri 12-20 value 4.52, published that Monday
-- The last two are the point-in-time rule: Friday's yield is not known until Monday.

with expected as (

    select check_name, expected_value
    from (
        values
            ('BTCUSDT daily close 2024-01-01', 44179.55),
            ('DGS10 known on 2024-12-22',      4.57),
            ('DGS10 known on 2024-12-23',      4.52)
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
