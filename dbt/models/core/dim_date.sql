-- One row per calendar day, weekends included: crypto trades every day (spec §10.3).
-- Starts at the FRED warm-up month (2018-12-01) and runs a year past today, so every trade_date
-- and observation_date in the warehouse has a row. MART_MACRO_DAILY starts from this
-- table so that Saturdays and Sundays get a macro value even though bond markets are closed.

with days as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="to_date('2018-12-01')",
        end_date="dateadd(year, 1, current_date())"
    ) }}

)

select
    date_day::date                     as date_day,
    year(date_day)                     as year,
    quarter(date_day)                  as quarter,
    month(date_day)                    as month,
    to_char(date_day, 'MMMM')          as month_name,
    weekiso(date_day)                  as week_of_year,
    dayofmonth(date_day)               as day_of_month,
    dayofweekiso(date_day)             as day_of_week,     -- 1 = Monday ... 7 = Sunday (ISO)
    dayname(date_day)                  as day_name,
    dayofweekiso(date_day) in (6, 7)   as is_weekend
from days
