# Upgrade audit (T0) — before the Research Copilot upgrade

Audited on 2026-10-22 at commit `92c84cc`, against `FinSight_AI_Research_Copilot_Upgrade_Spec.md` v1.1 (section 2.1).

## As-is architecture

The table in spec section 2.1 matches the code. Two flows:

- **Data (daily, Airflow `finsight_daily`, 00:30 UTC):** `scripts/load_binance.py` and `scripts/load_fred.py` →
  `src/ingestion/{binance,fred}/{client,extractor,loader,sync}.py` → shared `retrying_http.get_json` and
  `merge_loader.merge_rows` → `RAW.RAW_BINANCE_KLINE`, `RAW.RAW_FRED_SERIES`, `RAW.RAW_FRED_OBSERVATION` → `dbt source
  freshness` → dbt STAGING (views) → CORE (`dim_date`, `dim_asset`, `dim_macro_indicator`, `fct_crypto_kline_1h`
  incremental, `fct_macro_observation`) → MART (`mart_asset_daily`, `mart_macro_daily` point-in-time,
  `mart_market_macro_daily`).
- **Question:** `ui/streamlit_app.py` → `POST /ask` (`src/api/routes.py`) → `answer_question`
  (`src/agents/text_to_sql.py`) → LangGraph (`src/agents/graph.py`): `retrieve_context` → `generate_sql` →
  `validate_sql` (`SQLGuard`) → `execute_sql` (read-only `FINSIGHT_AGENT_SVC`, 30 s timeout) ↔ `repair_sql` (≤ 2).

Module dependencies the upgrade builds on:

| New work | Reuses |
|---|---|
| DefiLlama ingestion | `retrying_http.get_json`, the client/extractor/loader/sync layout, `merge_loader` patterns, `SnowflakeClient` |
| CPI | `src/ingestion/fred/*` unchanged; `MVP_SERIES`, seed `macro_indicators.csv`, `mart_macro_daily` point-in-time rule |
| Metric catalog | `semantic/metrics.yml`, `src/semantic/layer.py` (strict Pydantic), `src/semantic/retriever.py` |
| Research workflow | `SQLGuard`, `agent_warehouse()`, `LLMClient.generate_json`, `schema_tools.get_schema_context` |
| API/UI | `src/main.py` exception handler, `routes.py` conventions (`def`, `Depends`), Streamlit thin client |
| Evaluation | `eval/run_eval.py` (`wilson_interval`, `percentile`), `src/evaluation/compare.py` |

## Findings during the audit

| # | Finding | Impact | Action |
|---|---|---|---|
| 1 | The local `.venv` was missing (deleted outside the repo). | No command could run. | Recreated with Python 3.11 and `make install` (pinned versions). |
| 2 | **FRED is in maintenance**: every endpoint answers HTTP 200 with an HTML page. `get_json` calls `response.json()` and the loader dies with a raw `JSONDecodeError` traceback instead of a `SourceAPIError`. | `make load-fred` exits with a traceback; Airflow would retry and fail without a clear message. | Fixed in T1: a 200 that is not JSON is retried like a 5xx, then raises `SourceAPIError`. |
| 3 | FRED data stops at publication date 2026-10-05 (outage). `dbt source freshness` reports `ERROR STALE` for `raw_fred_observation`; `mart_macro_daily_treasury_value_is_recent` warns on 13 days. | Expected behaviour of the freshness design. | None; recovers when FRED is back. |
| 4 | Binance data had been loaded up to 2026-10-06 outside this session; caught up to 2026-10-22 02:00 UTC. | — | — |
| 5 | Items listed in spec section 2.4 (MART column descriptions, `docs/architecture.md`, `docs/README.vi.md`, CI runner label, FRED key rotation) are still open. | Documentation drift, prompt quality. | T2 (descriptions) and T6 (docs, CI). Key rotation is the owner's task. |

## Uncertainties and risks

- DefiLlama's free API publishes no rate limit or revision history; the design keeps one request per chain per run and
  builds its own vintages (spec 3.5).
- Upgrading `langgraph`, `openai`, `sqlglot` by several major versions may change APIs (T0.5); the SQL guard is the most
  exposed part.
- Live integration tests that call FRED fail while FRED is in maintenance; they are not part of CI.
