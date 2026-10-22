{# Column descriptions shared by the MART models. Each is written once and reused with
   {{ doc('name') }} in _marts.yml; persist_docs copies them into Snowflake COMMENTs, which is
   what the Text-to-SQL agent reads. Say what a value MEANS and its unit, with an example. #}

{% docs trade_date %}UTC calendar day of the asset's daily candle.{% enddocs %}

{% docs symbol %}Binance pair, e.g. BTCUSDT.{% enddocs %}

{% docs open_price %}Open of the day's first hourly candle, in USDT.{% enddocs %}

{% docs high_price %}Highest price of the day, in USDT.{% enddocs %}

{% docs low_price %}Lowest price of the day, in USDT.{% enddocs %}

{% docs close_price %}Close of the day's last hourly candle, in USDT.{% enddocs %}

{% docs base_volume %}Volume traded in the asset's own coin (e.g. BTC). Not comparable across assets.{% enddocs %}

{% docs quote_volume %}Value traded in USDT. Use this to compare trading activity across assets.{% enddocs %}

{% docs trade_count %}Number of trades in the day.{% enddocs %}

{% docs candle_count %}Hourly candles in the day; below 24 when Binance had an outage.{% enddocs %}

{% docs is_complete_day %}True when the day has all 24 hourly candles.{% enddocs %}

{% docs daily_return %}close_price / previous day's close_price - 1. 0.02 means +2%. Never SUM it over a period.{% enddocs %}

{% docs log_return %}ln(close_price / previous day's close_price). Log returns add up over days: period return = EXP(SUM(log_return)) - 1.{% enddocs %}

{% docs volatility_30d %}Realized volatility: sample standard deviation of the last 30 daily log returns, annualized with sqrt(365) because crypto trades every day. 0.5 means 50% a year. NULL for an asset's first 30 days.{% enddocs %}

{% docs fed_funds_rate %}Federal Funds Effective Rate in percent (4.33 = 4.33%), as known on that day.{% enddocs %}

{% docs fed_rate_source_date %}The day the fed_funds_rate value describes.{% enddocs %}

{% docs fed_rate_available_date %}The day FRED published the fed_funds_rate value; always on or before the row's day.{% enddocs %}

{% docs treasury_10y %}10-year US Treasury yield in percent (4.5 = 4.5%), as known on that day.{% enddocs %}

{% docs treasury_10y_source_date %}The bond-market day the treasury_10y value describes.{% enddocs %}

{% docs treasury_10y_available_date %}The day FRED published the treasury_10y value; always on or before the row's day.{% enddocs %}

{% docs treasury_10y_change_bps %}Change of the known 10-year yield since the previous calendar day, in basis points: 4.10% to 4.20% is +10. 0 on weekends and holidays.{% enddocs %}

{% docs days_since_observation %}Days between the row's day and the day the value describes; grows over weekends and holidays.{% enddocs %}

{% docs is_carried_forward %}True when nothing new was published on the row's day (weekend, holiday): the last known value is reused.{% enddocs %}

{% docs chain %}DefiLlama chain slug, e.g. Ethereum; "All" is DeFi on every chain together.{% enddocs %}

{% docs tvl_usd %}DeFi total value locked in USD at 00:00 UTC of the day (DefiLlama method: no liquid staking, no double counting). Not trading volume and not money flowing in.{% enddocs %}

{% docs chain_tvl_usd %}DeFi total value locked on the asset's own chain (ETH: Ethereum, SOL: Solana, BNB: BNB Smart Chain, BTC: Bitcoin), in USD at 00:00 UTC of trade_date.{% enddocs %}

{% docs defi_tvl_usd %}DeFi total value locked on all chains together, in USD at 00:00 UTC of trade_date.{% enddocs %}

{% docs tvl_change_1d %}tvl_usd / tvl_usd of the previous calendar day - 1. NULL when that day is missing.{% enddocs %}

{% docs tvl_change_7d %}TVL / TVL 7 calendar days earlier - 1. -0.1 means TVL fell 10% in a week. NULL when that day is missing.{% enddocs %}

{% docs is_retrospective %}True when the value was not available the day after tvl_date (historical backfill or a later revision): it is DefiLlama's current view, not what was known then.{% enddocs %}

{% docs fetched_date %}The day FinSight fetched the value shown.{% enddocs %}

{% docs cpi_month %}The CPI month (first day of the month) whose figures are shown: the newest month already published on the row's day.{% enddocs %}

{% docs cpi_release_date %}The day FRED published that CPI month for the first time; always on or before the row's day.{% enddocs %}

{% docs cpi_yoy_change %}US inflation: CPI of cpi_month / CPI of the same month a year earlier - 1, as published (0.031 = 3.1% a year). Monthly; carried forward between releases.{% enddocs %}

{% docs cpi_mom_change %}CPI of cpi_month / CPI of the month before - 1, as published (0.002 = +0.2% in the month).{% enddocs %}

