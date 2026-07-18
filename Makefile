.PHONY: install-python test lint format web-install web-build dev down

install-python:
	python -m pip install -e "apps/api[dev]" -e "services/grader[dev]"

test:
	python -m pytest apps/api/tests services/grader/tests

lint:
	python -m ruff check apps/api services/grader

format:
	python -m ruff format apps/api services/grader

web-install:
	cd apps/web && npm install

web-build:
	cd apps/web && npm run build

dev:
	docker compose up --build

down:
	docker compose down
