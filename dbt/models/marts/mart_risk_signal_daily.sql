-- Risk signals by fixed rules (spec v1.1, 4.6). Grain: trade_date + symbol + signal_id; one row
-- only when the signal fires. Rules, thresholds, windows and minimum observations come from the
-- risk_signal_rules seed. The language model never computes or invents a signal: it only reads
-- this table through the risk_signals catalog metric.
--
-- Every window ends on the signal day (drawdown) or the day before (the others): nothing after
-- the day is used. Windows are CALENDAR days through self-joins, so a missing day shrinks the
-- sample (and min_observations can then stop the signal) instead of silently stretching it.
-- high_correlation depends on which assets are in a watchlist and is computed with the brief.

with rules as (
    select * from {{ ref('risk_signal_rules') }}
),

daily as (
    select trade_date, symbol, close_price, daily_return, volatility_30d
    from {{ ref('mart_asset_daily') }}
),

abnormal_move as (
    select
        today.trade_date,
        today.symbol,
        'abnormal_move' as signal_id,
        abs(today.daily_return) / nullif(stddev_samp(past.daily_return), 0) as value,
        count(past.daily_return) as n_obs,
        null::boolean as is_retrospective
    from daily as today
    join rules on rules.signal_id = 'abnormal_move'
    join daily as past
        on  past.symbol = today.symbol
        and past.trade_date between dateadd('day', -rules.window_days, today.trade_date)
                                and dateadd('day', -1, today.trade_date)
    where today.daily_return is not null
    group by today.trade_date, today.symbol, today.daily_return
),

volatility_spike as (
    select
        today.trade_date,
        today.symbol,
        'volatility_spike' as signal_id,
        today.volatility_30d / nullif(median(past.volatility_30d), 0) as value,
        count(past.volatility_30d) as n_obs,
        null::boolean as is_retrospective
    from daily as today
    join rules on rules.signal_id = 'volatility_spike'
    join daily as past
        on  past.symbol = today.symbol
        and past.trade_date between dateadd('day', -rules.window_days, today.trade_date)
                                and dateadd('day', -1, today.trade_date)
    where today.volatility_30d is not null
    group by today.trade_date, today.symbol, today.volatility_30d
),

drawdown_alert as (
    select
        today.trade_date,
        today.symbol,
        'drawdown_alert' as signal_id,
        today.close_price / nullif(max(past.close_price), 0) - 1 as value,
        count(past.close_price) as n_obs,
        null::boolean as is_retrospective
    from daily as today
    join rules on rules.signal_id = 'drawdown_alert'
    join daily as past
        on  past.symbol = today.symbol
        and past.trade_date between dateadd('day', 1 - rules.window_days, today.trade_date)
                                and today.trade_date
    group by today.trade_date, today.symbol, today.close_price
),

-- Only chains mapped to an asset in dim_chain: a coin never gets TVL from a lookalike name.
tvl_drop as (
    select
        tvl_date as trade_date,
        related_symbol as symbol,
        'tvl_drop' as signal_id,
        tvl_change_7d as value,
        row_number() over (partition by chain order by tvl_date) as n_obs,
        is_retrospective
    from {{ ref('mart_chain_tvl_daily') }}
    where related_symbol is not null
),

candidates as (
    select * from abnormal_move
    union all select * from volatility_spike
    union all select * from drawdown_alert
    union all select * from tvl_drop
)

select
    c.trade_date,
    c.symbol,
    c.signal_id,
    rules.signal_name,
    c.value,
    rules.threshold,
    rules.comparison,
    rules.unit,
    rules.window_days,
    c.n_obs,
    c.is_retrospective
from candidates as c
join rules on rules.signal_id = c.signal_id
where c.value is not null
  and c.n_obs >= rules.min_observations
  and case rules.comparison
          when '>=' then c.value >= rules.threshold
          when '<=' then c.value <= rules.threshold
      end
