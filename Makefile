# Makefile convenience (POSIX shells). Windows users can use `make` via Git Bash or copy commands.

.DEFAULT_GOAL := help

PYTHON ?= python
VENV ?= .venv
ACTIVATE = . $(VENV)/Scripts/activate || . $(VENV)/bin/activate

## Colors
GREEN=\033[32m
YELLOW=\033[33m
RESET=\033[0m

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | sed -e 's/:.*##/\t- /' -e 's/^/ /'

venv: ## Create virtual environment if missing
	@if [ ! -d $(VENV) ]; then $(PYTHON) -m venv $(VENV); fi

install: venv ## Install runtime deps
	@$(ACTIVATE); pip install -U pip
	@$(ACTIVATE); pip install -r requirements.txt

install-dev: install ## Install dev deps
	@$(ACTIVATE); pip install -r requirements-dev.txt

playwright: ## Install playwright chromium browser
	@$(ACTIVATE); $(PYTHON) -m playwright install chromium --with-deps || true

lint: ## Ruff + mypy
	@$(ACTIVATE); ruff check .
	@$(ACTIVATE); mypy . || true

format: ## Auto-format (ruff fix + black)
	@$(ACTIVATE); ruff check . --fix
	@$(ACTIVATE); black .

format-check: ## Check formatting (non destructive)
	@$(ACTIVATE); ruff check .
	@$(ACTIVATE); black --check .

test: ## Run fast test suite
	@$(ACTIVATE); pytest -q --maxfail=1 --disable-warnings

coverage: ## Run coverage with report
	@$(ACTIVATE); pytest --cov=scraper --cov=server --cov-report=xml:coverage.xml --cov-report=term-missing
	@$(ACTIVATE); $(PYTHON) scripts/generate_badge.py || true

show-config: ## Show effective runtime configuration
	@$(ACTIVATE); $(PYTHON) scripts/show_config.py

server: ## Launch API server (reload)
	@$(ACTIVATE); uvicorn server.main:app --reload --port 8000

worker: ## Launch scraping worker
	@$(ACTIVATE); $(PYTHON) -m scraper.worker

run-all: ## Launch server + worker sequentially (basic)
	@$(ACTIVATE); $(PYTHON) scripts/run_all.py

build-desktop: ## Build desktop app (Windows or macOS shell specifics may apply)
	@$(ACTIVATE); $(PYTHON) build_windows.py || echo 'Implement custom desktop build wrapper if needed.'

clean: ## Remove caches and build artifacts
	rm -rf .pytest_cache .mypy_cache ruff_cache build dist *.egg-info coverage.xml coverage_badge.svg

.PHONY: help venv install install-dev playwright lint format format-check test coverage show-config server worker run-all build-desktop clean
