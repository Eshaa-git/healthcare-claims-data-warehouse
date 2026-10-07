SHELL := /bin/bash
.DEFAULT_GOAL := help

-include .env
export

COMPOSE := docker compose
CLI := $(COMPOSE) exec -T airflow /opt/claims-dw/venv/bin/claims-dw
HOST_DB := WAREHOUSE_HOST=127.0.0.1 WAREHOUSE_PORT=$(or $(WAREHOUSE_HOST_PORT),55432)

.PHONY: help setup lock up seed pipeline test report down reset lint screenshots

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

setup: ## Check runtime and .env, install locked dependencies, validate config
	@command -v docker >/dev/null || { echo "Docker with Compose is required"; exit 1; }
	@docker compose version >/dev/null
	@command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
	@scripts/check_env.sh
	uv sync --frozen
	uv export --frozen --no-dev --no-emit-project --format requirements-txt -q -o requirements.lock.txt
	uv run claims-dw check-config

lock: ## Re-resolve dependencies and refresh requirements.lock.txt
	uv lock
	uv export --frozen --no-dev --no-emit-project --format requirements-txt -q -o requirements.lock.txt

up: ## Build the image, start services (waits for health checks), apply migrations
	$(COMPOSE) up -d --build --wait
	$(CLI) migrate

seed: ## Download CMS archives (checksums verified) and build the cohort extracts
	$(CLI) acquire --run-id seed-$$(date -u +%Y%m%dT%H%M%SZ)
	$(CLI) cohort --run-id seed-$$(date -u +%Y%m%dT%H%M%SZ)

pipeline: ## Trigger the Airflow DAG and wait; exits nonzero if the run fails
	scripts/run_dag.sh

test: ## Unit tests, then integration/e2e tests against the running warehouse (test database)
	uv run pytest tests/unit
	$(HOST_DB) CLAIMS_DW_EVIDENCE_DIR=reports/evidence uv run pytest tests/integration

report: ## Write reports/metrics.json and reports/summary.md for the latest run
	$(CLI) report

screenshots: ## Capture dashboard and Airflow screenshots with headless Chrome
	scripts/screenshots.sh

lint: ## Ruff lint and format check
	uv run ruff check src tests dags app
	uv run ruff format --check src tests dags app

down: ## Stop services; database volumes are kept
	$(COMPOSE) down

reset: ## DESTRUCTIVE: delete database volumes and processed extracts (asks first)
	@read -p "Delete warehouse + Airflow volumes and data/processed? Type 'reset': " ans; \
	  [ "$$ans" = reset ] || { echo "cancelled"; exit 1; }
	$(COMPOSE) down -v
	rm -rf data/processed data/manifest
