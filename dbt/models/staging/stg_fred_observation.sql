-- FRED observation vintages, with the validity period of each vintage filled in.
-- Grain: series_id + observation_date + realtime_start (tested in _staging.yml).
-- RAW keeps only realtime_start (the day FRED published a value). A vintage stays the latest
-- known value until the day before the next vintage of the same date; the current one is
-- open-ended (9999-12-31), which is FRED's own convention.

with source as (

    select * from {{ source('raw', 'raw_fred_observation') }}

),

vintages as (

    select
        series_id,
        observation_date,

        realtime_start,
        coalesce(
            dateadd(
                'day',
                -1,
                lead(realtime_start) over (
                    partition by series_id, observation_date
                    order by realtime_start
                )
            ),
            '9999-12-31'::date
        )                                         as realtime_end,

        value_raw,
        value,
        -- FRED writes "." for a day with no value (e.g. a bond-market holiday).
        value is null                             as is_missing,

        ingested_at                               as loaded_at,
        batch_id

    from source

)

select * from vintages
