
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

# Helpers
define exists
which $(1) >/dev/null 2>&1
endef

help: ## Show help for each target
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

setup: ## Create venv and install deps (uv/poetry/pip fallback)
	@if $(call exists,$(UV)); then \
		$(UV) venv && . .venv/bin/activate && $(UV) pip install -e . && $(UV) pip install -r requirements-dev.txt || true ; \
	else \
		if [ -f poetry.lock ] || [ -f pyproject.toml ]; then \
			poetry install --with dev ; \
		else \
			$(PY) -m venv .venv && . .venv/bin/activate && $(PIP) install -r requirements.txt && $(PIP) install -r requirements-dev.txt || true ; \
		fi \
	fi
	@echo "✅ setup complete"

dev: ## Run api + worker + deps via docker-compose
	$(COMPOSE) up -d
	$(COMPOSE) ps
	@echo "▶ tailing logs (Ctrl+C to detach)"
	$(COMPOSE) logs -f api worker

down: ## Stop and remove containers
	$(COMPOSE) down -v

migrate: ## Run Alembic migrations
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

demo: ## End-to-end: ingest → parse → curate (LS) → export
	@if [ -x scripts/demo.sh ]; then \
		bash scripts/demo.sh ; \
	elif [ -f scripts/demo.py ]; then \
		$(PY) scripts/demo.py ; \
	else \
		echo "No demo script found. Add scripts/demo.sh or scripts/demo.py"; exit 1; \
	fi

clean: ## Remove build cache & __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache dist build || true

.PHONY: help setup dev down migrate lint test scorecard demo clean
