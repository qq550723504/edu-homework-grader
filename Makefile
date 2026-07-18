.PHONY: install-python test lint format api-test api-lint api-migrate web-install web-build dev down

install-python:
	python -m pip install -e "apps/api[dev]" -e "services/grader[dev]"

test:
	python -m pytest apps/api/tests services/grader/tests

api-test:
	python -m pytest apps/api/tests

api-lint:
	python -m ruff format --check apps/api
	python -m ruff check apps/api

api-migrate:
	python -m alembic -c apps/api/alembic.ini upgrade head

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
