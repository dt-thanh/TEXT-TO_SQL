-- One row per CPI month: the value as FIRST published and the changes an analyst could compute
-- on that publication day (spec v1.1, 4.2). Grain: cpi_month.
--
-- CPI is revised after publication (seasonal factors are recomputed every February). A change
-- "as published" divides the new month by the previous month and the same month a year earlier
-- AS KNOWN ON THE RELEASE DATE (the vintage valid that day), never by later revisions.
-- latest_cpi_index is today's view of the month, for comparison; is_revised says if they differ.
-- Months of 2017 only serve as the base of 2018's year-over-year change.
-- A month published without a value keeps its row with cpi_index NULL: October 2025 was never
-- collected (US government shutdown) and FRED published it as "." on 2025-12-18, together with
-- November. Changes that need a missing month are NULL, never filled in.

with cpi as (

    select observation_date, value, realtime_start, realtime_end
    from {{ ref('fct_macro_observation') }}
    where series_id = 'CPIAUCSL'

),

first_release as (

    select
        observation_date  as cpi_month,
        value             as cpi_index,
        realtime_start    as release_date
    from cpi
    qualify row_number() over (partition by observation_date order by realtime_start) = 1

)

select
    first_release.cpi_month,
    first_release.release_date,
    first_release.cpi_index,
    first_release.cpi_index / month_before.value - 1  as cpi_mom_change,
    first_release.cpi_index / year_before.value - 1   as cpi_yoy_change,
    latest.value                                      as latest_cpi_index,
    latest.value <> first_release.cpi_index           as is_revised

from first_release
left join cpi as month_before
    on  month_before.observation_date = dateadd('month', -1, first_release.cpi_month)
    and month_before.realtime_start <= first_release.release_date
    and month_before.realtime_end   >= first_release.release_date
left join cpi as year_before
    on  year_before.observation_date = dateadd('month', -12, first_release.cpi_month)
    and year_before.realtime_start <= first_release.release_date
    and year_before.realtime_end   >= first_release.release_date
left join cpi as latest
    on  latest.observation_date = first_release.cpi_month
    and latest.realtime_end = '9999-12-31'
where first_release.cpi_month >= '2018-01-01'
