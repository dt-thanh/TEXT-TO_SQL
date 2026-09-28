# Common local commands. Always run through the project venv, never the system Python.
PY := .venv/bin/python
# dbt reads Snowflake settings from environment variables: export everything in .env, then run
# dbt from inside dbt/ so it finds dbt_project.yml and profiles.yml there.
DBT := set -a && . ./.env && set +a && cd dbt && ../.venv/bin/dbt
# Airflow runs in Docker (airflow/docker-compose.yml). AIRFLOW_UID=$(id -u) makes the containers
# run as you, so files they write into the repo stay yours.
AIRFLOW := AIRFLOW_UID=$$(id -u) docker compose -f airflow/docker-compose.yml

.PHONY: install run test test-unit lint check-snowflake load-binance load-fred \
	dbt-deps dbt-build dbt-docs airflow-up airflow-down airflow-check airflow-logs ask \
	prompt eval eval-gold

install:
	$(PY) -m pip install -r requirements.txt

run:
	$(PY) -m uvicorn src.main:app --reload

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

dbt-deps:
	$(DBT) deps

# Extra dbt flags: make dbt-build ARGS="--full-refresh" or ARGS="--select fct_crypto_kline_1h"
dbt-build:
	$(DBT) build $(ARGS)

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

# Ask a question in plain language: make ask Q="BTC biến động thế nào tuần trước?"
ask:
	$(PY) -m scripts.ask "$(Q)"

# Print what the model would read for Q (schema + semantic context): no LLM call, no cost.
prompt:
	$(PY) -m scripts.ask --prompt "$(Q)"

# Benchmark the agent (execution accuracy). ~1 LLM call per question, see eval/run_eval.py.
eval:
	$(PY) -m eval.run_eval $(ARGS)

# Only check that every gold SQL still runs: no LLM, no cost.
eval-gold:
	$(PY) -m eval.run_eval --gold-only
