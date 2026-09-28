-- FRED series metadata (title, units, frequency) as FRED describes each series.
-- Grain: series_id. Exists so CORE never reads RAW directly: every layer reads only the one below.

with source as (

    select * from {{ source('raw', 'raw_fred_series') }}

)

select
    series_id,
    title,
    frequency,
    frequency_short,
    units,
    seasonal_adjustment,
    observation_start,
    observation_end,
    source_last_updated,
    ingested_at as loaded_at
from source
