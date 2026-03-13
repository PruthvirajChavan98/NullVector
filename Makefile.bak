UV ?= uv

.PHONY: setup format format-check lint typecheck test ci

setup:
	$(UV) sync --extra dev

format:
	$(UV) run ruff format src tests

format-check:
	$(UV) run ruff format --check src tests

lint:
	$(UV) run ruff check src tests

typecheck:
	$(UV) run mypy src tests

test:
	$(UV) run pytest

ci: format-check lint typecheck test

