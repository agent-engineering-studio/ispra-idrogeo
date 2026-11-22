.PHONY: start stop app app-up help check lint format typecheck test build docs docs-serve live benchmark benchmark-record \
	test-notebooks up down restart ps logs health notebooks cli shell \
	docker-build docker-test-notebooks clean eval

# Containers. Every name starts with NAME, so copies never clash:
#   make up NAME=idrogeo-dev IDROGEO_MCP_PORT=8768
# Defaults can also go in a .env file (see .env.example).
-include .env
NAME ?= $(or $(IDROGEO_NAME),ispra-idrogeo)
IDROGEO_MCP_PORT ?= 8767
IDROGEO_JUPYTER_PORT ?= 8888
IDROGEO_JUPYTER_TOKEN ?= idrogeo
export IDROGEO_NAME := $(NAME)
export IDROGEO_MCP_PORT IDROGEO_JUPYTER_PORT IDROGEO_JUPYTER_TOKEN
# The Claude API key, from .env or the shell: only `make eval` uses it.
export ANTHROPIC_API_KEY
IDROGEO_APP_PORT ?= 3002
export IDROGEO_APP_PORT
COMPOSE := docker compose --profile notebooks --profile tools --profile app
NOTEBOOK_TEST := examples/00-test-the-library.ipynb

help:  ## List the commands
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t 24

# Development

check: lint typecheck test  ## ruff + mypy --strict + pytest, the CI gate

lint:  ## ruff check and format check
	uv run ruff check
	uv run ruff format --check

format:  ## Format the code and fix what ruff can
	uv run ruff format
	uv run ruff check --fix

typecheck:  ## mypy --strict
	uv run mypy

test:  ## The tests, offline (mocked transport)
	uv run pytest --cov --cov-report=term-missing

build:  ## The wheel and sdist
	uv build

docs:  ## Build the documentation site, llms-full.txt and SKILL.md
	uv run --group docs zensical build --strict
	uv run python tools/build_llms.py

docs-serve:  ## Serve the documentation site locally
	uv run --group docs zensical serve

live:  ## The contract tests against the live IdroGEO service (network)
	uv run pytest -m live

benchmark:  ## The known cases, offline from the cassettes (as in CI)
	uv run python -m benchmarks.run --check

benchmark-record:  ## Re-record the cassettes from the live service, then the results
	uv run python -m benchmarks.record
	uv run python -m benchmarks.run --record

test-notebooks:  ## Run the test notebook against the live service, here
	uv run --group notebooks jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=600 $(NOTEBOOK_TEST)

app:  ## The Mappa dei dati, here: http://127.0.0.1:3002
	sh app/vendor.sh
	uv run --group app uvicorn --factory app.api:create_app --host 127.0.0.1 --port 3002

# Containers

app-up:  ## The Mappa dei dati in a container: http://localhost:$(IDROGEO_APP_PORT)
	docker compose --profile app up --build --detach app
	@echo "Mappa dei dati: http://localhost:$(IDROGEO_APP_PORT) (container $(NAME)-app)"

start: docker-build up app-up notebooks  ## Build every image and start everything: MCP, map, Jupyter
	@echo ""
	@echo "MCP server: http://localhost:$(IDROGEO_MCP_PORT)/mcp"
	@echo "Mappa dei dati: http://localhost:$(IDROGEO_APP_PORT)"
	@echo "Jupyter: http://localhost:$(IDROGEO_JUPYTER_PORT)/lab?token=$(IDROGEO_JUPYTER_TOKEN)"

stop: down  ## Stop everything started by make start (the data volume stays)

docker-build:  ## Build the images
	$(COMPOSE) build

up:  ## Start the MCP server: http://localhost:$(IDROGEO_MCP_PORT)/mcp
	docker compose up --build --detach --wait mcp
	@echo "MCP server: http://localhost:$(IDROGEO_MCP_PORT)/mcp (container $(NAME)-mcp)"

notebooks:  ## Start Jupyter with the examples
	docker compose --profile notebooks up --build --detach notebooks
	@echo "Jupyter: http://localhost:$(IDROGEO_JUPYTER_PORT)/lab?token=$(IDROGEO_JUPYTER_TOKEN) (container $(NAME)-notebooks)"

docker-test-notebooks:  ## Run the test notebook inside a container
	docker compose --profile notebooks run --rm --build --name $(NAME)-notebook-test notebooks \
		jupyter nbconvert --to notebook --execute --inplace \
		--ExecutePreprocessor.timeout=600 00-test-the-library.ipynb

cli:  ## Run the idrogeo command: make cli ARGS="hazard 40.829 14.617"
	docker compose --profile tools run --rm --name $(NAME)-cli-$$$$ cli $(ARGS)

shell:  ## A shell in the MCP server container
	docker compose exec mcp bash

health:  ## Ask the MCP server if it is up
	@curl -fsS http://localhost:$(IDROGEO_MCP_PORT)/health && echo

ps:  ## The containers of this copy
	$(COMPOSE) ps

logs:  ## Follow the logs
	$(COMPOSE) logs --follow

restart: down up  ## Stop, then start again

down:  ## Stop and remove the containers (the data volume stays)
	$(COMPOSE) down

clean:  ## Remove containers, images and the data volume of this copy
	$(COMPOSE) down --volumes --rmi local

# The agent eval: Claude on idrogeo-mcp (costs API calls). ARGS="--limit 5" for a pilot.
eval:  ## The agent eval of Claude on idrogeo-mcp (paid API calls): make eval ARGS="--limit 5"
	uv run --group evals python -m evals.run $(ARGS)
