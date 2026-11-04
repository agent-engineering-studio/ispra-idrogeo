.PHONY: check lint format typecheck test build live

check: lint typecheck test

lint:
	uv run ruff check
	uv run ruff format --check

format:
	uv run ruff format
	uv run ruff check --fix

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing

build:
	uv build

# The contract with the live IdroGEO service: needs the network (weekly in CI).
live:
	uv run pytest -m live
