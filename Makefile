# Common local commands. Always run through the project venv, never the system Python.
PY := .venv/bin/python

.PHONY: install run test test-unit lint check-snowflake

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
