# Upgrade baseline (T0)

Measured on 2026-10-22 at commit `92c84cc`, fresh `.venv` (Python 3.11.15) with the pinned versions:
`langgraph 0.4.5`, `openai 1.78.1`, `sqlglot 26.19.0`, `dbt-core 1.12.5`, `dbt-snowflake 1.12.1`, `fastapi 0.115.12`,
`streamlit 1.64.0`. LLM: `gpt-4o-mini`. Warehouse: `FINSIGHT_WH` (XSMALL).

## Data state

| Table | State |
|---|---|
| `RAW.RAW_BINANCE_KLINE` | 259,390 candles, newest open_time 2026-10-22 02:00 UTC |
| `RAW.RAW_FRED_OBSERVATION` | DFF 2,863 rows, DGS10 2,048 rows; newest publication 2026-10-05 (FRED in maintenance) |
| `MART.MART_ASSET_DAILY` | 10,816 rows, newest trade_date 2026-10-21 |

## Commands and results

| Command | Exit | Result |
|---|---|---|
| `make ci` (ruff, unit tests, `dbt parse`) | 0 | ruff clean; 237 passed |
| `pytest` (all) | 1 | 274 passed, 1 skipped (DAG test, needs Airflow), 2 failed: `test_fred_api.py` live tests, FRED in maintenance |
| `make dbt-build` | 0 | PASS=81 WARN=2 ERROR=0 (warns: 32 short Binance candles; 13 days of 10-year yield older than 7 days) |
| `make dbt-freshness` | 1 | Binance PASS; FRED ERROR STALE (outage) |
| `make eval-gold` | 0 | 18 gold SQL ran; 3 questions are must-decline |
| `make eval` | 0 | see below |

## Benchmark (`eval/results/run_20261022T035246Z.json`)

| Metric | Value |
|---|---|
| Execution accuracy | 17/21 = 81% [95% CI 60–92%] |
| Dev | 11/15 = 73% [48–89%] |
| Holdout | 6/6 = 100% [61–100%] |
| SQL that passed the guard and ran | 18/18 |
| Repairs | 1 question, fixed |
| Cost | $0.0077 total, $0.00037 per question |
| Latency (whole question) | p50 3.2 s, p95 6.9 s |

Failures (all dev): q10 and q14 (missing the expected metric column), q16 (4 rows instead of 2), q18 (100 rows instead
of 1).

The previous recorded run (`run_20260929T041135Z`, 2026-09-29) was 18/21 with p50 2.4 s / p95 6.2 s. The difference is
within run-to-run variation (one dev question flips between runs; the confidence intervals overlap). This run is the
baseline the upgrade is compared against.
