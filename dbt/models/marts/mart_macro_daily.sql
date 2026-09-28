-- One row per calendar day with the macro values an analyst could actually KNOW that day
-- (spec §11.2, §12, §13). Grain: market_date.
--
-- Point-in-time rule, for every day X and every indicator:
--   1. keep the vintages already published on X  (realtime_start <= X)
--   2. that were still the current value on X    (realtime_end   >= X, i.e. not yet revised)
--   3. that carry a number                       (not a "." holiday)
--   4. take the one with the newest observation_date.
-- Weekends and holidays therefore reuse the last published value; the *_is_carried_forward and
-- *_days_since_observation columns make that visible instead of hiding it.
--
-- ASSUMPTION: a value FRED published on day X (US time; DFF and DGS10 are out by the US
-- afternoon) was known before day X ended in UTC, so it may sit next to that day's crypto
-- close (23:59:59 UTC).

with calendar as (

    select date_day as market_date
    from {{ ref('dim_date') }}
    where date_day between '2019-01-01' and current_date()

),

known_values as (

    select
        indicators.indicator_id,
        observations.observation_date,
        observations.value,
        observations.realtime_start,
        observations.realtime_end
    from {{ ref('fct_macro_observation') }} as observations
    join {{ ref('dim_macro_indicator') }} as indicators
        on indicators.series_id = observations.series_id
    where not observations.is_missing

),

latest_known as (

    select
        calendar.market_date,
        known_values.indicator_id,
        known_values.value,
        known_values.observation_date  as source_date,
        known_values.realtime_start    as available_date
    from calendar
    join known_values
        on  known_values.realtime_start <= calendar.market_date
        and known_values.realtime_end   >= calendar.market_date
    qualify row_number() over (
        partition by calendar.market_date, known_values.indicator_id
        order by known_values.observation_date desc
    ) = 1

)

select
    calendar.market_date,

    fed.value                                               as fed_funds_rate,
    fed.source_date                                         as fed_rate_source_date,
    fed.available_date                                      as fed_rate_available_date,
    datediff('day', fed.source_date, calendar.market_date)  as fed_rate_days_since_observation,
    fed.available_date < calendar.market_date               as fed_rate_is_carried_forward,

    t10.value                                               as treasury_10y,
    t10.source_date                                         as treasury_10y_source_date,
    t10.available_date                                      as treasury_10y_available_date,
    datediff('day', t10.source_date, calendar.market_date)  as treasury_10y_days_since_observation,
    t10.available_date < calendar.market_date               as treasury_10y_is_carried_forward

from calendar
left join latest_known as fed
    on  fed.market_date = calendar.market_date
    and fed.indicator_id = 'FED_FUNDS'
left join latest_known as t10
    on  t10.market_date = calendar.market_date
    and t10.indicator_id = 'TREASURY_10Y'
