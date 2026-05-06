PYTHON ?= python3.12
VENV   := .venv
UV     := uv
APP    := app

.PHONY: help install dev infra-up infra-down test test-unit test-integration lint type fmt smoke clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?##"};{printf "  %-20s %s\n", $$1, $$2}'

install: ## Create venv via uv and install dev deps
	$(UV) venv $(VENV) --python $(PYTHON)
	$(UV) pip install --python $(VENV)/bin/python -e ".[dev]"

infra-up: ## Start local Mongo + Redis (docker compose)
	docker compose -f infra/docker-compose.yml up -d
	@echo "Waiting for Mongo healthcheck..."
	@until docker compose -f infra/docker-compose.yml exec -T mongo mongosh --quiet --eval 'db.runCommand({ping:1})' >/dev/null 2>&1; do sleep 1; done
	@echo "Mongo + Redis ready."

infra-down: ## Stop local infra
	docker compose -f infra/docker-compose.yml down

dev: ## Run the bot in long-poll mode (foreground)
	$(VENV)/bin/python -m $(APP)

api: ## Run the FastAPI server (separate process from the bot)
	$(VENV)/bin/uvicorn app.api:app --host 127.0.0.1 --port 8002 --reload

verifier-install: ## Install the Node verifier sidecar deps
	cd webapp_verifier && npm install

verifier: ## Run the Node verifier sidecar (foreground)
	cd webapp_verifier && npm start

webapp-install: ## Install the React Mini App deps
	cd webapp && npm install

webapp: ## Run the Mini App in dev mode (vite, port 5173)
	cd webapp && npm run dev

webapp-test: ## Run the Mini App test suite (vitest)
	cd webapp && npm test

webapp-build: ## Production build of the Mini App
	cd webapp && npm run build

test: test-unit ## Default: run unit tests (fast)

test-unit:
	$(VENV)/bin/pytest -q -m unit

test-integration: ## Real Bot API + real testnet RPC + real Mongo/Redis. Requires .env populated.
	$(VENV)/bin/pytest -q -m integration

lint:
	$(VENV)/bin/ruff check $(APP) tests

fmt:
	$(VENV)/bin/ruff format $(APP) tests
	$(VENV)/bin/ruff check --fix $(APP) tests

type:
	$(VENV)/bin/pyright

smoke: ## Print the Session 0 smoke procedure from RUNBOOK
	@grep -A 200 "## Session 0" RUNBOOK.md | head -100

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache **/__pycache__
