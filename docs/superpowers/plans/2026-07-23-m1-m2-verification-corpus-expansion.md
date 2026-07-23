# M1/M2 Verification Corpus Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce and supply at least 20 deterministic M1 and 20 deterministic M2 verification cases for issue #83.

**Architecture:** Keep the JSON corpus as declarative scenario data and materialize each case through the existing real `run_candidate_verification` test adapter. The runner will reject an undersized or malformed corpus before evaluation and will print deterministic per-type, per-finding summaries; it does not introduce a second validator or change production behavior.

**Tech Stack:** Python 3.13+, pytest, existing SQLAlchemy test fixtures, existing deterministic Grader doubles, JSON, GNU Make.

## Global Constraints

- Do not modify production validator, provider, database schema, acceptance policy, #42 evaluation thresholds, or #43 governance behavior.
- Each type has at least 20 distinct cases covering valid answers, incorrect answers, empty/unsupported assertions, boundaries, common misconceptions, consistency mismatches, and deterministic service failures where applicable.
- A case failure names its JSON ID, expected versus actual status, and only stable Finding Codes; it never prints candidate content, final answers, MathJSON, prompts, or provider diagnostics.
- `make verification-regression` remains the single discoverable command and must fail when either type drops below 20 cases.

---

### Task 1: Guard the corpus contract and add meaningful M1/M2 scenarios

**Files:**

- Modify: `apps/api/tests/test_verification_corpus.py:22-151`
- Modify: `apps/api/tests/fixtures/verification_corpus/m1.json:1-12`
- Modify: `apps/api/tests/fixtures/verification_corpus/m2.json:1-12`

**Interfaces:**

- Consumes corpus objects with `version`, `question_type`, `cases`, `id`, `scenario`, `expected_status`, and `expected_codes`.
- Produces a test failure for fewer than 20 cases and output shaped as `verification corpus findings: M1 code=... total=...` followed by the existing type summary.
- `_run_case()` continues to call the existing verification service; its scenario mapping stays test-only.

- [ ] **Step 1: Write the failing lower-bound and diagnostic tests.**

  In `test_m1_m2_verification_corpus_runs_with_stable_type_summaries`, require `len(cases) >= 20`; collect `Counter` values from every returned Finding Code; and assert failures with:

  ```python
  assert status == expected_status, (
      f"{case_id}: expected status={expected_status}, actual status={status}, "
      f"finding_codes={codes}"
  )
  ```

  Run `python -m pytest apps/api/tests/test_verification_corpus.py -q -s`. Expected: FAIL because both existing corpora contain five cases.

- [ ] **Step 2: Expand the M1 corpus and adapter scenarios.**

  Add 15 uniquely named M1 cases spanning decimal/negative/zero values, inclusive tolerance boundaries, outside boundaries, incorrect and empty answers, misconception answers, explanation suffix mismatch, invalid answer text, score mismatch, unexpected MathJSON, and missing assertions. Extend `_m1_candidate()` to create only those candidate and rule variations, preserving the real verifier call. Expected codes must be only stable existing codes.

- [ ] **Step 3: Expand the M2 corpus and adapter scenarios.**

  Add 15 uniquely named M2 cases spanning an alternate valid display value, a fractional maximum score, wrong MathJSON, malformed/empty MathJSON, explanation suffix mismatch, score mismatch, missing assertions, unsupported assertion shapes, a common algebra misconception, and deterministic probe failures. Extend `_m2_candidate()` / grader selection only where the real verifier needs a deterministic distinguishable normalizer or probe response.

- [ ] **Step 4: Run focused regression.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
  python -m pytest apps/api/tests/test_verification_corpus.py -q -s
  make verification-regression
  ```

  Expected: PASS; both type summaries report `total=20`, and each emitted Finding Code total is deterministic.

- [ ] **Step 5: Run affected verification tests and commit the narrow PR slice.**

  ```powershell
  python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_verification_corpus.py -q
  python -m ruff check apps/api/tests/test_verification_corpus.py
  python -m ruff format --check apps/api/tests/test_verification_corpus.py
  git diff --check
  git add apps/api/tests/fixtures/verification_corpus/m1.json apps/api/tests/fixtures/verification_corpus/m2.json apps/api/tests/test_verification_corpus.py docs/superpowers/plans/2026-07-23-m1-m2-verification-corpus-expansion.md
  git commit -m "test: expand m1 m2 verification corpus"
  ```

## Plan self-review

- Spec coverage: Task 1 covers #83's per-type minimum, M1/M2 valid/invalid/empty/boundary/misconception probes, stable diagnostics, and the single runner command without entering E1-E4, dependency-failure, #42, or #43 scope.
- Placeholder scan: no deferred implementation or generic testing steps remain.
- Type consistency: JSON fields are consumed by the existing `_corpus()` and `_run_case()` functions; the new `Counter` is local to the runner test.

## Delivery verification — 2026-07-23

- Red test: the runner failed with `M1: expected at least 20 deterministic cases` while each corpus still contained five cases; unknown scenarios also failed until explicit scenario allowlists were added.
- `make verification-regression` with explicit package source paths: exit 0; M1 total=20 passed=20 failed=0 and M2 total=20 passed=20 failed=0, with deterministic Finding Code totals.
- `python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_verification_corpus.py -q` with the same source paths: exit 0; 210 passed.
- `python -m ruff check apps/api/tests/test_verification_corpus.py`, `python -m ruff format --check apps/api/tests/test_verification_corpus.py`, and `git diff --check`: exit 0.
