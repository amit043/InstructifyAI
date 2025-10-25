
# Makefile — Phase-1 Dataset Factory (FastAPI + Celery + Postgres + Redis + MinIO)

SHELL := /bin/bash
.ONESHELL:
.EXPORT_ALL_VARIABLES:

PY ?= python3
PIP ?= pip
UV  ?= uv

# Paths
COMPOSE ?= docker compose
ALEMBIC ?= alembic

# Prefer native podman-compose if available; otherwise fallback to `podman compose`
PODMAN_COMPOSE := $(shell if command -v podman-compose >/dev/null 2>&1; then echo podman-compose; else echo podman compose; fi)

# Helpers
define exists
which $(1) >/dev/null 2>&1
endef

help: ## Show help for each target
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: ## Create venv and install deps (uv/poetry/pip fallback)
	@if $(call exists,$(UV)); then \
		$(UV) venv && . .venv/bin/activate && $(UV) pip install -e . && $(UV) pip install -r requirements-dev.txt ; \
	else \
		if [ -f poetry.lock ] || [ -f pyproject.toml ]; then \
			poetry install --with dev ; \
		else \
			$(PY) -m venv .venv && . .venv/bin/activate && $(PIP) install -r requirements.txt && $(PIP) install -r requirements-dev.txt ; \
		fi \
	fi
	@echo "✅ setup complete"

dev: ## Run api + worker + deps via docker-compose
	$(COMPOSE) up -d
	$(MAKE) dev-migrate
	$(COMPOSE) ps
	@echo "▶ tailing logs (Ctrl+C to detach)"
	$(COMPOSE) logs -f api worker

# ------------------------------------------------------------------
# ML (gen/trainer) — auto CPU/GPU selection
# ------------------------------------------------------------------
build-ml-auto: ## Build ML image (gen/trainer) with auto GPU/CPU selection
	ML_VARIANT=$$(command -v nvidia-smi >/dev/null 2>&1 && echo gpu || echo cpu) \
		$(COMPOSE) build gen trainer

up-ml-auto: ## Start ML services with auto GPU/CPU selection
	ML_VARIANT=$$(command -v nvidia-smi >/dev/null 2>&1 && echo gpu || echo cpu) \
		$(COMPOSE) up -d gen trainer

dev-ml-auto: ## Build+start ML services (auto GPU/CPU)
	$(MAKE) build-ml-auto
	$(MAKE) up-ml-auto

# Podman variants
build-ml-auto-podman: ## Build ML image with Podman (auto GPU/CPU)
	@echo "Using compose provider: $(PODMAN_COMPOSE)"
	ML_VARIANT=$$(command -v nvidia-smi >/dev/null 2>&1 && echo gpu || echo cpu) \
		COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) build gen trainer

up-ml-auto-podman: ## Start ML services with Podman (auto GPU/CPU)
	@echo "Using compose provider: $(PODMAN_COMPOSE)"
	ML_VARIANT=$$(command -v nvidia-smi >/dev/null 2>&1 && echo gpu || echo cpu) \
		COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) up -d gen trainer

dev-ml-auto-podman: ## Build+start ML services with Podman (auto GPU/CPU)
	$(MAKE) build-ml-auto-podman
	$(MAKE) up-ml-auto-podman

dev-podman: ## Run stack using Podman Compose (migrations inside api container)
	@echo "Using compose provider: $(PODMAN_COMPOSE)"
	COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) up -d
	COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) exec -T api alembic upgrade head
	COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) ps
	@echo "▶ tailing logs (Ctrl+C to detach)"
	COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) logs -f api worker

down-podman: ## Stop and remove containers (Podman)
	COMPOSE_PROVIDER=podman $(PODMAN_COMPOSE) down -v

dev-adapters: ## Run stack with adapters API enabled (override compose)
	$(COMPOSE) -f docker-compose.yml -f docker-compose.adapters.yml up -d
	$(MAKE) dev-migrate
	$(COMPOSE) -f docker-compose.yml -f docker-compose.adapters.yml ps
	@echo "▶ tailing logs (Ctrl+C to detach)"
	$(COMPOSE) -f docker-compose.yml -f docker-compose.adapters.yml logs -f api worker

down: ## Stop and remove containers
	$(COMPOSE) down -v

down-adapters: ## Stop stack started with dev-adapters
	$(COMPOSE) -f docker-compose.yml -f docker-compose.adapters.yml down -v

migrate: ## Run Alembic migrations
	$(ALEMBIC) upgrade head

dev-migrate: ## Run Alembic migrations on dev startup
	$(ALEMBIC) upgrade head

lint: ## Run black, isort, mypy
	@echo "▶ black"
	$(PY) -m black .
	@echo "▶ isort"
	$(PY) -m isort .
	@echo "▶ mypy"
	$(PY) -m mypy . || true

test: ## Run unit and e2e tests
	@command -v coverage >/dev/null 2>&1 \
		&& coverage run -m pytest tests/test_semantic_search.py -q \
		&& coverage xml \
		&& command -v coverage-badge >/dev/null 2>&1 \
		&& coverage-badge -f -o coverage.svg \
	|| pytest tests/test_semantic_search.py -q

scorecard: ## Run golden-set scorecard
	$(PY) scripts/generate_bundles.py
	$(PY) scripts/scorecard.py --path examples/bundles

cli: ## Run instructify CLI (use ARGS="<cmd> ...")
	$(PY) scripts/instructify_cli.py $(ARGS)

demo: ## End-to-end: ingest → parse → curate (LS) → export
	@if [ -x scripts/demo.sh ]; then \
		bash scripts/demo.sh ; \
	elif [ -f scripts/demo.py ]; then \
		$(PY) scripts/demo.py ; \
	else \
		echo "No demo script found. Add scripts/demo.sh or scripts/demo.py"; exit 1; \
	fi

demo-investor: ## 7-minute investor/customer walkthrough (doc-scoped multi-teacher)
	bash scripts/demo_investor.sh

clean: ## Remove build cache & __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build || true

.PHONY: help setup dev dev-adapters down down-adapters migrate dev-migrate lint test scorecard cli demo demo-investor clean dev-podman down-podman build-ml-auto up-ml-auto dev-ml-auto build-ml-auto-podman up-ml-auto-podman dev-ml-auto-podman
