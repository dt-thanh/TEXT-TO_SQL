# Common local commands. Always run through the project venv, never the system Python.
PY := .venv/bin/python
# dbt reads Snowflake settings from environment variables: export everything in .env, then run
# dbt from inside dbt/ so it finds dbt_project.yml and profiles.yml there.
DBT := set -a && . ./.env && set +a && cd dbt && ../.venv/bin/dbt

.PHONY: install run test test-unit lint check-snowflake load-binance load-fred \
	dbt-deps dbt-build dbt-docs

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

dbt-build:
	$(DBT) build

dbt-docs:
	$(DBT) docs generate
	$(DBT) docs serve --port 8080
