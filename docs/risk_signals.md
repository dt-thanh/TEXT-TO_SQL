# Risk signals

Signals are fixed rules computed in dbt (`mart_risk_signal_daily`). The rules, thresholds,
windows and minimum observations are in [`dbt/seeds/risk_signal_rules.csv`](../dbt/seeds/risk_signal_rules.csv).
The language model never computes or invents a signal. It can only read rows of this table
through the `risk_signals` catalog metric. A signal describes past data. It is not a forecast
and not investment advice, and the brief says so in a line that the code adds, not the writer.

| Rule | Value compared with the threshold | Default | Window, minimum |
|---|---|---|---|
| `abnormal_move` | \|daily return\| ÷ sample sd of the daily returns of the previous 90 days | ≥ 3 sd | 90 days before the day, ≥ 60 |
| `volatility_spike` | 30-day volatility ÷ its median over the previous 180 days | ≥ 2.0 (was 1.5) | 180 days before the day, ≥ 120 |
| `drawdown_alert` | close ÷ highest close of the last 90 days − 1 | ≤ −20% | 90 days with the day, ≥ 30 |
| `tvl_drop` | 7-day change of DeFi TVL on the chain mapped to the asset (`dim_chain`) | ≤ −15% | ≥ 30 days of TVL |
| `high_correlation` | correlation of daily returns of two watchlist assets over the brief's period | ≥ 0.90 | ≥ 25 common days; computed with the brief |

Windows are calendar days, and every window ends on the signal day or the day before, so no rule
uses later data. When a day is missing, the sample shrinks and the minimum can stop the signal;
the window is never silently stretched.

## Tests

- **dbt unit tests** (mocked inputs, run by `dbt build`):
  - a −20% drawdown fires and −19% does not, using `<=` on exact NUMBER arithmetic (RISK-02);
  - an asset with one day of history gets no signal (RISK-03);
  - the abnormal-move sd uses only the days before the signal day, so a large move does not
    raise its own threshold, and the normal day after it does not fire (RISK-01, RISK-04);
  - TVL of "All chains" never becomes an asset signal (DYN-08).
- **Known answers on real data** (RISK-01):
  - the `risk_signals` golden rows of `semantic/metrics.yml` and `eval/brief_cases.jsonl` were
    computed in plain Python from `MART_ASSET_DAILY` and `MART_CHAIN_TVL_DAILY` with the
    seed's rules, not from `mart_risk_signal_daily`;
  - the mart reproduces them exactly: 11 rule × asset results for BTC, ETH and SOL in 2025, and
    the signals of 4 brief cases.

## How often each rule fires (RISK-05)

Measured on 2026-10-26 over all history, using `make risk-frequency`. The share is days fired ÷
eligible days, where eligible means the rule had its full window behind it.

| Rule | BTC | ETH | SOL | BNB | Reading |
|---|---:|---:|---:|---:|---|
| `abnormal_move` (≥ 3 sd) | 2.0% | 1.8% | 1.4% | 2.0% | An event. A normal distribution would give 0.27%; crypto's fat tails give about 7 times that, roughly once every 7 weeks per asset. Kept. |
| `volatility_spike` (at the old ≥ 1.5) | 8.8% | 8.1% | 8.5% | 15.0% | **Too frequent for an event** (above 5%). At ≥ 1.75: 4.8 / 2.8 / 4.5 / 8.3%. At ≥ 2.0: 2.2 / 1.6 / 1.5 / 5.5%. |
| `drawdown_alert` (≤ −20%) | 32.1% | 44.6% | 61.8% | 36.4% | **A state, not an event**: crypto spends long stretches 20% below its 90-day high. Even ≤ −40% gives 4.9 / 12.7 / 25.9 / 9.0%. |
| `tvl_drop` (≤ −15%) | 3.6% | 5.1% | 5.3% | 2.2% | Borderline. TVL history before the daily loads is retrospective. |

### Owner decisions (2026-10-26)

A threshold changes only through a review, with its reason written here. It is never adjusted
to fit a known answer. After a change, the `risk_signals` golden rows and
`eval/brief_cases.jsonl` are recomputed from the independent calculation
(`python -m eval.brief_expected`).

1. **`volatility_spike`: 1.5 → 2.0.** At 1.5 it fired on 8–15% of days, too often for an event.
   At 2.0 it fires on 2.2% (BTC), 1.6% (ETH), 1.5% (SOL) and 5.4% (BNB). BNB is borderline and
   is watched. The golden rows were recomputed: in 2025, BTC, ETH and SOL have no volatility
   spike at 2.0. All 14 template golden cases pass, and so do the 4 no-LLM brief cases.
2. **`drawdown_alert`: kept as a state.** The brief shows how many days it fired and the last
   day: "this asset has been 20% or more below its 90-day high". It is not presented as a new
   event. If an event is wanted later, add a separate "onset" rule that fires on the first day
   the drawdown crosses −20%.
