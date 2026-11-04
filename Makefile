.PHONY: check lint format typecheck test build docs docs-serve eval

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

docs:
	uv run --group docs mkdocs build --strict

docs-serve:
	uv run --group docs mkdocs serve

# The agent eval: Claude on idrogeo-mcp (costs API calls). ARGS="--limit 5" for a pilot.
eval:
	uv run --group evals python -m evals.run $(ARGS)
