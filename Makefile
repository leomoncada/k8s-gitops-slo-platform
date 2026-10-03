SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help
KIND ?= kind
export KIND
VENV := .venv
PY := $(VENV)/bin/python

# incident-% stays out of .PHONY: make skips pattern rules for phony targets.
.PHONY: help doctor up sync down urls test test-app test-alerts slos lint incidents demo

help: ## List targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

doctor: ## Check that the required tools are installed
	@scripts/doctor.sh

up: ## Build the whole platform in kind (OVERLAYS="kind ci" for CI sizing)
	@scripts/up.sh

sync: ## Publish local changes to the in-cluster Git repo so Argo CD applies them
	@scripts/sync.sh

down: ## Delete the kind cluster
	@$(KIND) delete cluster --name slo-platform

urls: ## Print the local URLs
	@printf '  Grafana       http://localhost:30300\n  Prometheus    http://localhost:30090\n  Alertmanager  http://localhost:30093\n  Argo CD       http://localhost:30080\n  orders API    http://localhost:30800\n  Tempo API     http://localhost:30320\n  Git (Argo CD) http://localhost:30232/platform.git\n'

$(VENV): app/requirements-dev.txt tests/requirements.txt
	python3 -m venv $(VENV)
	$(PY) -m pip install --quiet -r app/requirements-dev.txt -r tests/requirements.txt
	@touch $(VENV)

test: test-app test-alerts ## App tests and alert-logic tests (no cluster needed)

test-app: $(VENV) ## orders service tests against a throwaway Postgres
	$(PY) -m pytest app/tests -q

test-alerts: ## promtool unit tests for every alert rule
	@scripts/test-alerts.sh

slos: ## Regenerate SLO rules from slos/orders.yaml
	@scripts/generate-slos.sh

lint: $(VENV) ## Lint Python, shell, charts and generated files
	@scripts/lint.sh

incidents: $(VENV) ## Run all six incidents against the running cluster
	$(PY) -m pytest tests/incidents -s -v -p no:cacheprovider

incident-%: $(VENV) ## Run one incident with narration, e.g. make incident-1
	$(PY) -m pytest tests/incidents/test_0$*_*.py -s -v -p no:cacheprovider

demo: ## up, then incident #1 narrated
	@scripts/up.sh
	@$(MAKE) --no-print-directory incident-1
