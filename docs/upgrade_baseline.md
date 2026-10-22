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

## T0.5 — dependency upgrade and model A/B (2026-10-22)

Upgraded one package at a time, running the unit tests after each:

| Package | Before | After | What changed in our code |
|---|---|---|---|
| `sqlglot` | 26.19.0 | 30.24.0 | The FROM argument was renamed (`from` → `from_`), so the guard silently stopped checking FROM sources: `SELECT ... FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())` passed. Caught by `test_table_functions_cannot_go_around_the_allowlist`. The guard now checks every `From`/`Join` node, independent of argument names; two more cases (`JOIN TABLE(...)`, `VALUES`) are tested. |
| `openai` | 1.78.1 | 3.36.0 | `max_tokens` → `max_completion_tokens` (the only cap newer models accept). Reasoning models (gpt-5 family) reject `temperature=0`: `LLM_REASONING_EFFORT` switches to `reasoning_effort` and gives hidden reasoning tokens room. |
| `langgraph` | 0.4.5 | 1.2.16 | Default recursion limit went from 25 to 10,007 steps; `RECURSION_LIMIT = 25` is now passed explicitly. |
| `dbt-core` | 1.12.5 | 1.12.6 | None (`dbt-core-experimental-parser` 2.0.8, pinned to match in `airflow/Dockerfile`). |

After the upgrade (gpt-4o-mini): all unit tests pass, `dbt build` PASS=81 WARN=2, integration tests unchanged
(only the two live FRED tests fail, FRED in maintenance), DAG tests 3/3 with Airflow 3.3.2.

Model A/B, same 21 questions, three runs per model, prices from developers.openai.com/api/docs/pricing:

| Model | Correct per run | Holdout (3 runs) | p50 | p95 | $ per question |
|---|---|---|---|---|---|
| gpt-4o-mini | 19, 20, 19 | 18/18 | 3.3 s | 9.7–15.1 s | 0.00040–0.00044 |
| **gpt-4.1-mini** | **20, 20, 20** | **18/18** | **1.8–2.0 s** | **2.5–3.1 s** | 0.00089 |
| gpt-5-mini (`reasoning_effort=minimal`) | 17, 18, 18 | 16/18 | 3.9–4.3 s | 5.9–7.2 s | 0.00082–0.00093 |

Decision: **gpt-4.1-mini** becomes the default. Holdout is not lower, it is the only model that gave the same
answers on all three runs, and p95 latency drops from 10–15 s to about 3 s, for about twice the price (still under
$0.001 per question). The differences in accuracy are within the confidence intervals; latency and stability are not.
Reports: `eval/results/run_20261022T0358*.json` to `run_20261022T0410*.json`.
