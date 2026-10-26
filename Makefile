# Common local commands. Always run through the project venv, never the system Python.
PY := .venv/bin/python
# dbt reads Snowflake settings from environment variables: export everything in .env, then run
# dbt from inside dbt/ so it finds dbt_project.yml and profiles.yml there.
DBT := set -a && . ./.env && set +a && cd dbt && ../.venv/bin/dbt
# Airflow runs in Docker (airflow/docker-compose.yml). AIRFLOW_UID=$(id -u) makes the containers
# run as you, so files they write into the repo stay yours.
AIRFLOW := AIRFLOW_UID=$$(id -u) docker compose -f airflow/docker-compose.yml

.PHONY: install run ui app-up app-down ci test test-unit lint check-snowflake load-binance load-fred load-defillama \
	add-asset onboard-assets refresh-binance-catalog brief eval-brief eval-chat risk-frequency dbt-deps dbt-build dbt-parse dbt-freshness dbt-docs airflow-up airflow-down airflow-check airflow-logs ask \
	prompt research eval eval-gold eval-research

install:
	$(PY) -m pip install -r requirements-dev.txt

# The API on http://localhost:8000 (docs: /docs). Restarts when code changes.
run:
	$(PY) -m uvicorn src.main:app --reload --host 127.0.0.1 --port 8000

# The Streamlit screen on http://127.0.0.1:8501 (another port: make ui UI_PORT=8502).
# Needs the API running (make run).
UI_PORT ?= 8501
ui:
	$(PY) -m streamlit run ui/streamlit_app.py --server.address 127.0.0.1 --server.port $(UI_PORT)

# API + UI in Docker (docker-compose.yml at the repository root).
app-up:
	docker compose up -d --build

app-down:
	docker compose down

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

check-snowflake:
	$(PY) -m scripts.check_snowflake

test-unit:
	$(PY) -m pytest tests/unit

load-binance:
	$(PY) -m scripts.load_binance

load-fred:
	$(PY) -m scripts.load_fred

load-defillama:
	$(PY) -m scripts.load_defillama

dbt-deps:
	$(DBT) deps

# Extra dbt flags: make dbt-build ARGS="--full-refresh" or ARGS="--select fct_crypto_kline_1h"
dbt-build:
	$(DBT) build $(ARGS)

# Does the dbt project compile (SQL, Jinja, refs, tests)? Does not query Snowflake.
dbt-parse:
	$(DBT) parse

# The offline checks CI runs on every push (.github/workflows/ci.yml), before you push.
ci: lint test-unit dbt-parse

# Is RAW data recent enough? (limits in dbt/models/staging/_sources.yml)
dbt-freshness:
	$(DBT) source freshness

dbt-docs:
	$(DBT) docs generate
	$(DBT) docs serve --port 8082

# Build the image if needed and start Airflow in the background. UI: http://localhost:8081
airflow-up:
	$(AIRFLOW) up -d --build

airflow-down:
	$(AIRFLOW) down

# Lists DAG files Airflow failed to import (empty output = all good).
airflow-check:
	$(AIRFLOW) exec airflow-scheduler airflow dags list-import-errors

airflow-logs:
	$(AIRFLOW) logs -f --tail 100 airflow-scheduler

# Check coins and add the right ones (a typo gets suggestions): make add-asset SYMBOL="link avax arbb"
add-asset:
	$(PY) -m scripts.onboard_assets add $(SYMBOL)

# Run the onboarding steps by hand, without Airflow: verify + backfill, dbt, mark ready.
onboard-assets:
	$(PY) -m scripts.onboard_assets load; test $$? -ne 1
	$(DBT) build --select binance_assets dim_asset+ stg_binance_kline+
	$(PY) -m scripts.onboard_assets finalize

# Refresh CONTROL.BINANCE_SYMBOL (Binance USDT spot pairs) by hand; Airflow does it daily.
refresh-binance-catalog:
	$(PY) -m scripts.onboard_assets refresh-catalog

# Daily brief of every watchlist, saved in CONTROL.DAILY_BRIEF (~$0.002 each).
# make brief ARGS="--watchlist default --print"   ·   ARGS="--no-llm --print" costs nothing.
brief:
	$(PY) -m scripts.daily_brief $(ARGS)

# Ask a question in plain language: make ask Q="BTC biến động thế nào tuần trước?"
ask:
	$(PY) -m scripts.ask "$(Q)"

# Research question → Markdown report with evidence: make research Q="..." (~2-3 LLM calls).
research:
	$(PY) -m scripts.research "$(Q)"

# Print what the model would read for Q (schema + semantic context): no LLM call, no cost.
prompt:
	$(PY) -m scripts.ask --prompt "$(Q)"

# Benchmark the agent (execution accuracy). ~1 LLM call per question, see eval/run_eval.py.
eval:
	$(PY) -m eval.run_eval $(ARGS)

# Benchmark research mode (eval/research_questions.jsonl). ARGS="--gold-only" costs nothing.
eval-research:
	$(PY) -m eval.run_research_eval $(ARGS)

# Benchmark the chat (follow-ups, greetings, out of scope). ARGS="--gold-only" costs nothing.
eval-chat:
	$(PY) -m eval.run_chat_eval $(ARGS)

# How often each risk rule fires on real data (docs/risk_signals.md). No LLM.
risk-frequency:
	$(PY) -m scripts.risk_signal_frequency

# Benchmark the Daily Brief (eval/brief_cases.jsonl). ARGS="--no-llm" costs nothing.
eval-brief:
	$(PY) -m eval.run_brief_eval $(ARGS)

# Only check that every gold SQL still runs: no LLM, no cost.
eval-gold:
	$(PY) -m eval.run_eval --gold-only
