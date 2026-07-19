.PHONY: install-python test lint format api-test api-lint api-migrate question-test calibration-report web-install web-build dev down

install-python:
	python -m pip install -e packages/processor-policy -e "apps/api[dev]" -e "services/grader[dev]"

test:
	python -m pytest apps/api/tests services/grader/tests

api-test:
	python -m pytest apps/api/tests

api-lint:
	python -m ruff format --check apps/api
	python -m ruff check apps/api

api-migrate:
	python -m alembic -c apps/api/alembic.ini upgrade head

question-test:
	python -m pytest apps/api/tests/test_policies.py apps/api/tests/test_question_models.py apps/api/tests/test_question_versions.py apps/api/tests/test_question_runs.py apps/api/tests/test_questions.py

calibration-report:
	python -m edu_grader.calibration services/grader/tests/fixtures/english_calibration.jsonl

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
