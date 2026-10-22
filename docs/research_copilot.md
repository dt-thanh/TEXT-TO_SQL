# Research Copilot upgrade (2026-10-22)

FinSight grew from "question → one SQL query" into a research assistant for crypto markets, US
rates and DeFi, without replacing the Text-to-SQL core: `POST /ask` and its screen behave as
before. Plan: `FinSight_AI_Research_Copilot_Upgrade_Spec.md` v1.1. Baseline, dependency upgrade
and model choice: [upgrade_baseline.md](upgrade_baseline.md). Audit: [upgrade_audit.md](upgrade_audit.md).

## What changed

| Area | Change |
|---|---|
| Dependencies | sqlglot 30, openai 3, langgraph 1.2, dbt-core 1.12.6. The sqlglot upgrade would have blinded the SQL guard to `TABLE(...)` sources; the guard now checks every FROM/JOIN node. |
| Model | gpt-4.1-mini by a three-run A/B against gpt-4o-mini and gpt-5-mini. Reasoning models are supported through `LLM_REASONING_EFFORT`. |
| Ingestion | DefiLlama daily TVL for Ethereum, Solana, BSC, Bitcoin and all chains (`make load-defillama`, Airflow task `load_defillama`). Today's unfinished point and the leading zero days are dropped; gaps stay gaps. Each fetch stores only new or revised values, so the table is its own revision history. FRED maintenance pages (HTML with status 200) are retried and end in a clear error. |
| Warehouse | `stg_defillama_chain_tvl`, `dim_chain`, `fct_chain_tvl`, `mart_chain_tvl_daily` (1-day and 7-day change on calendar days, `is_retrospective`); `treasury_10y_change_bps`; the asset's chain TVL and total DeFi TVL next to each asset-day. Every MART column has a description, enforced by a dbt test (10 of 12 columns of the main table had none). |
| Catalog | Nine research metrics in `semantic/metrics.yml` with SQL templates, typed parameters, units, sample size, point-in-time mode and a golden case checked by an independent Python calculation. |
| Research mode | `src/agents/research`: plan (strict JSON, metric id is an enum) → resolve and run templates (guard, read-only role) → write findings → grounding check in code → Markdown report. Status decided by code. Budgets: 4 tasks, 2 writes, 60 s, $0.01. |
| Serving | `POST /research`, a Research tab with the report and a Markdown download, `make research Q="..."`. |
| Evaluation | 12 new Quick SQL questions (q22–q33) and a 19-question research benchmark (`make eval-research`), both committed before the agent answered them. |
| CI | Runners pinned to ubuntu-24.04; the Docker smoke test loads the research prompts and catalog. |

## Results

| Benchmark | Before (2026-10-22 baseline) | After |
|---|---|---|
| Quick SQL, execution accuracy | 17/21, holdout 6/6, p50 3.2 s / p95 6.9 s, gpt-4o-mini | 32/33 (12 new questions), holdout 14/14, p50 1.9 s / p95 2.9 s, gpt-4.1-mini, $0.0014 per question |
| Research, 19 questions | — | 19/19, holdout 9/9 [70–100%]; metric selection 15/15, values 24/24, grounded 15/15, refusals 4/4; p50 3.3 s / p95 5.3 s; $0.0016 per question |
| Tests | 276 Python, 70 dbt | 377 Python, 97 dbt |

Reports: `eval/results/run_20261022T043344Z.json`, `eval/results/research_20261022T081243Z.json`.
Quick SQL cost per question rose (from $0.0009 with gpt-4.1-mini on the old schema) because the
prompt now carries the TVL table and a description for every column.

## Gap log

| Item | Status | Why, and what to do |
|---|---|---|
| CPI (`CPIAUCSL`) | Not done | FRED served a maintenance page for every request during the whole upgrade. Adding the series to the seed before RAW has it would fail `dim_macro_indicator` tests and turn the daily run red. When FRED is back: add `CPIAUCSL` to `MVP_SERIES` (`src/ingestion/fred/sync.py`) and to `dbt/seeds/macro_indicators.csv`, run `make load-fred`, add a monthly mart with first-release values and release dates, a `cpi_mom_change` catalog metric with a golden case, and known answers. |
| Intent router | Replaced by an explicit mode | The user chooses Quick SQL or Research (tab or endpoint). A misrouted question costs a wrong kind of answer; an explicit choice costs one click. |
| Streaming progress | P2 | Research answers take about 2–12 s (the first call of a process includes the Snowflake login), inside the UI's 120 s timeout. |
| Wording quality | Not graded | Grounding guarantees numbers, not interpretation. Reading answers found two wording problems (conclusions from a median, repeated caveats), fixed and moved r12 to dev; looser phrasing can remain. Evidence and SQL are shown next to every finding. |
| Holdout authorship | Partial | The new holdout questions were written by the builder before any run. Questions written by someone else would be a stronger test. |
| FRED key rotation | Owner | The key once leaked to a log before secret masking existed. |
