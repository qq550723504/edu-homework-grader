.PHONY: install-python test lint format api-test api-lint api-migrate question-test calibration-report ai-evaluation ai-evaluation-operational verification-regression docs-check web-install web-test web-build web-e2e dev down

install-python:
	python -m pip install -e packages/processor-policy -e "services/generator[openai,dev]" -e "apps/api[dev]" -e "services/grader[dev]"

test:
	python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests

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

ai-evaluation:
	python -m edu_grader_api.services.ai_evaluation_gate apps/api/tests/fixtures/ai_evaluation/gate-policy-v1.json apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl artifacts/ai-evaluation

ai-evaluation-operational:
	test -n "$(SPEC)" || (echo "SPEC=/secure/path/operational-spec.json is required" >&2; exit 1)
	python -m edu_grader_api.services.ai_evaluation_operational "$(SPEC)" "$(or $(OUTPUT),artifacts/ai-evaluation-operational)"

verification-regression:
	python -m pytest apps/api/tests/test_verification_corpus.py -q -s

docs-check:
	python scripts/check_docs_status.py

lint:
	python -m ruff format --check packages/processor-policy services/generator apps/api services/grader
	python -m ruff check packages/processor-policy services/generator apps/api services/grader

format:
	python -m ruff format packages/processor-policy services/generator apps/api services/grader

web-install:
	cd apps/web && npm ci

web-test:
	cd apps/web && npm test

web-build:
	cd apps/web && npm run build

web-e2e:
	cd apps/web && npx playwright install chromium && npm run test:e2e

dev:
	docker compose up --build

down:
	docker compose down
