-- One row per macro indicator (spec §10.5): our business naming (seed) joined to FRED's own
-- metadata (units, frequency, title). Each fact comes from the source that owns it.

with indicators as (

    select * from {{ ref('macro_indicators') }}

),

fred_series as (

    select * from {{ ref('stg_fred_series') }}

)

select
    indicators.indicator_id,
    indicators.series_id,
    indicators.indicator_name,
    indicators.category,
    fred_series.units                 as unit,
    fred_series.frequency,
    'FRED'                            as source,
    indicators.description,
    fred_series.title                 as source_title,
    fred_series.seasonal_adjustment,
    fred_series.source_last_updated
from indicators
left join fred_series
    on fred_series.series_id = indicators.series_id
