# Common local commands. TODO: Add format, type-check, and integration-test targets.
.PHONY: install run test lint gen-data

install:
	python3.11 -m pip install -r requirements.txt

run:
	python3.11 -m uvicorn src.main:app --reload

test:
	python3.11 -m pytest

lint:
	python3.11 -m ruff check .

gen-data:
	python3.11 data/generate_data.py
