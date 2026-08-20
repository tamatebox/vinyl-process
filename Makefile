# Development entry points. Everything here is what CI runs.
PYTHON ?= python
VENV   ?= .venv
BIN    := $(VENV)/bin

.PHONY: help install check lint format typecheck test cov schemas examples clean

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "%-12s %s\n", $$1, $$2}'

install:  ## create the venv and install with dev extras
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -e ".[dev]"

check: lint typecheck test  ## everything CI checks

lint:  ## ruff check + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format:  ## apply ruff's fixes and formatting
	$(BIN)/ruff check . --fix
	$(BIN)/ruff format .

typecheck:  ## mypy (strict on src/)
	$(BIN)/mypy

test:  ## run the test suite
	$(BIN)/python -m pytest

cov:  ## run the test suite with branch coverage
	$(BIN)/python -m pytest --cov

schemas:  ## regenerate the committed JSON Schemas from the models
	$(BIN)/vinyl-process schemas -o schemas/

examples:  ## regenerate examples/ by running the real pipeline
	$(BIN)/python scripts/regenerate_examples.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
