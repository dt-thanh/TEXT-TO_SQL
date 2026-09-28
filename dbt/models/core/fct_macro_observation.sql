-- Every published value of every macro series, with the period it was the latest known value
-- (spec §10.2). Grain: series_id + observation_date + realtime_start.
--
-- A full table rebuild, not incremental: a NEW vintage changes the realtime_end of the OLD one,
-- so "only process new rows" would leave stale end dates behind. It is a few thousand rows.

select
    series_id,
    observation_date,
    value,
    is_missing,
    realtime_start,
    realtime_end,
    loaded_at
from {{ ref('stg_fred_observation') }}
