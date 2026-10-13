# Makefile
# Short commands for common tasks. Run `make` to list them.
.DEFAULT_GOAL := help
COMPOSE = docker compose

.PHONY: help init build up down restart logs ps test lint format docs docs-build clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

init: ## Create .env from the template (only if it does not exist)
	@test -f .env || (cp .env.example .env && echo "Created .env - review it, then run: make up")

build: init ## Build all Docker images
	$(COMPOSE) build

up: init ## Build (if needed) and start the platform in the background
	$(COMPOSE) up -d --build

down: ## Stop the platform (data volumes are kept)
	$(COMPOSE) down

restart: down up ## Stop, then start again

logs: ## Follow logs of all services (Ctrl+C to leave)
	$(COMPOSE) logs -f --tail=100

ps: ## Show running containers and their health
	$(COMPOSE) ps

test: ## Run automated tests (activate your virtualenv first)
	pytest

lint: ## Check code style and docstrings
	ruff check .
	ruff format --check .

format: ## Auto-fix code style
	ruff check --fix .
	ruff format .

docs: ## Serve the documentation site at http://localhost:8001
	mkdocs serve -a localhost:8001

docs-build: ## Build the static documentation site into ./site
	mkdocs build

clean: ## DANGER: stop everything and DELETE all stored data volumes
	$(COMPOSE) down -v --remove-orphans

test-docker: ## Run tests inside a Linux container (use this if Windows blocks pyarrow)
	docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v "$(CURDIR):/work" -w /work python:3.12-slim sh -c "pip install -q -r services/ingestion/requirements.txt -r services/cleaning/requirements.txt plotly pyyaml pytest && pytest -p no:cacheprovider"

psql: ## Open a SQL shell in the warehouse
	docker compose exec warehouse sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

dags: ## List Airflow DAGs and show any import errors
	docker compose exec airflow airflow dags list
	docker compose exec airflow airflow dags list-import-errors

integration: ## Run end-to-end tests in a separate throw-away stack (needs Docker)
	docker compose --env-file .env.example -f docker-compose.integration.yml -p taxi-it up -d --build --wait --wait-timeout 900
	docker run --rm --network taxi-it_default -e IT_INGESTION_URL=http://ingestion:8000 -e IT_CLEANING_URL=http://cleaning:8000 -e IT_ETL_URL=http://etl:8000 -e IT_ANALYTICS_URL=http://analytics:8000 -e IT_QUALITY_URL=http://quality:8000 -v "$(CURDIR):/work" -w /work python:3.12-slim sh -c "pip install -q httpx pyarrow pytest && pytest --noconftest -m integration tests/integration -p no:cacheprovider"; status=$$?; docker compose --env-file .env.example -f docker-compose.integration.yml -p taxi-it down -v; exit $$status