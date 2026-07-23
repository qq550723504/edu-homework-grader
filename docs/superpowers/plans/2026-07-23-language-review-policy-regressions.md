# Language and Review-Policy Regressions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 20 deterministic E1, E2, E3, and E4 regression cases to the existing #83 corpus runner.

**Architecture:** Extend the test-only scenario adapter with existing candidate fixtures and deterministic Grader doubles. The real verification service remains the execution target; E3/E4 cases also assert their draft remains `pending_review` after verification.

**Tech Stack:** Python 3.13+, pytest, JSON, SQLAlchemy test fixtures, existing verification service and Grader doubles.

## Global Constraints

- No production-code, migration, automatic acceptance/publication, #42, or #43 changes.
- Every E type has at least 20 named scenarios and expected stable Finding Codes.
- E3/E4 are never treated as published or automatically accepted; the corpus asserts `pending_review`.
- Unknown scenarios and undersized corpus files fail without candidate contents in diagnostics.

---

### Task 1: Extend the deterministic corpus to E1–E4

**Files:**

- Create: `apps/api/tests/fixtures/verification_corpus/e1.json`
- Create: `apps/api/tests/fixtures/verification_corpus/e2.json`
- Create: `apps/api/tests/fixtures/verification_corpus/e3.json`
- Create: `apps/api/tests/fixtures/verification_corpus/e4.json`
- Modify: `apps/api/tests/test_verification_corpus.py`

**Interfaces:**

- Consumes `{version, question_type, cases}` corpus files and scenario records with `id`, `scenario`, `expected_status`, `expected_codes`, and optional `expected_teacher_state`.
- Produces real validation-run status/code assertions and sanitized type summaries through `make verification-regression`.

- [ ] **Step 1: Write failing E-type corpus lower-bound tests.**

  Extend the runner type loop to `E1`–`E4` and require all four fixture files. Run the corpus command. Expected: FAIL because the files do not exist.

- [ ] **Step 2: Add E1/E2 scenarios and materializers.**

  Add 20 cases each for accepted variants, invalid/missing values, normalized duplicates, and E2 Grader response failures. Use existing E2 Grader doubles and a local E1 fixture; run every case through `run_candidate_verification`.

- [ ] **Step 3: Add E3/E4 scenarios and teacher-state assertions.**

  Add 20 cases each for clean and warning language, grammar dependency failures, reading-material/rubric/score conflicts, and E4 probe failures. Assert E3/E4 drafts remain `pending_review` after validation.

- [ ] **Step 4: Verify and commit.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
  make verification-regression
  python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_verification_corpus.py -q
  python -m ruff check apps/api/tests/test_verification_corpus.py
  python -m ruff format --check apps/api/tests/test_verification_corpus.py
  git diff --check
  ```

  Expected: every type reports `total=20`, E3/E4 remain `pending_review`, and all commands exit 0.

## Delivery verification — 2026-07-23

- Red test: extending the type loop to E1–E4 failed because `e1.json` did not exist.
- `make verification-regression` with explicit package source paths: exit 0; M1, M2, E1, E2, E3, and E4 each report `total=20 passed=20 failed=0` with stable Finding Code summaries.
- The E3/E4 corpus records require and observed `pending_review` after every validation run; no corpus path accepts or publishes a draft.
- `python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_verification_corpus.py -q`: exit 0; 236 passed.
- `python -m ruff check apps/api/tests/test_verification_corpus.py`, `python -m ruff format --check apps/api/tests/test_verification_corpus.py`, and `git diff --check`: exit 0.
