# AI Candidate Question Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist immutable verification runs and expose deterministic, explainable M1/E1 findings for AI-generated candidate-question drafts.

**Architecture:** Add verification-run and finding records that attach only to `GeneratedQuestionDraft`, never to `QuestionVersion`. A service evaluates a persisted candidate with deterministic curriculum, schema, safety, duplicate, M1, and E1 rules; it persists every invocation as a new run and converts unexpected validator failures to a safe blocked finding. A small tenant-scoped API triggers a run and reads its immutable results. Teacher acceptance enforcement and non-deterministic/advanced validators remain outside this slice.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, Alembic, FastAPI, Pydantic, existing processor-policy validation, existing HTTP grader client, pytest, Ruff.

## Global constraints

- A validation run is append-only: rerunning a draft creates a new ordinal run and never mutates an earlier run or its findings.
- All validation evidence must be teacher-readable and must not contain provider secrets, raw exception text, or sensitive unsafe-content excerpts.
- `blocked` is the conservative result for policy/schema failures and for any unexpected validator failure.
- This slice validates all persisted candidate drafts through generic rules, plus M1 and E1 type-specific rules. M2, E2-E4, semantic similarity, external language tooling, copyright analysis, golden-case certification, batch-acceptance enforcement, and UI are explicitly deferred.
- Reuse the existing `validate_policy` and `HttpGraderClient`; do not introduce a second policy grammar or a second grading protocol.

## Task 1: Add immutable validation persistence

**Files:**

- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0016_ai_question_validation_runs.py`
- Modify: `apps/api/tests/test_curriculum_models.py`
- Create: `apps/api/tests/test_question_validation_models.py`

- [ ] **Step 1: Write failing persistence tests.**

  Cover a validation run associated with a `GeneratedQuestionDraft`, a child finding, and two runs for the same draft with distinct `run_number` values. Assert that neither model has a `QuestionVersion` foreign key and that the Alembic head expected by the model test advances to `0016_ai_question_validation_runs`.

- [ ] **Step 2: Add model enums and tables.**

  In `models.py`, add a run status enum with `passed`, `warning`, and `blocked`; add a finding severity enum with `warning` and `blocked`. Add `GenerationValidationRun` with:

  ```python
  generated_question_draft_id: Mapped[uuid.UUID]
  generation_job_id: Mapped[uuid.UUID]
  run_number: Mapped[int]
  validator_version: Mapped[str]
  ruleset_version: Mapped[str]
  status: Mapped[ValidationRunStatus]
  feature_summary_json: Mapped[dict[str, Any]]
  ```

  Add `ValidationFinding` with a run foreign key, stable `code`, `severity`, structured `evidence_json`, bounded `remediation`, and creation timestamp. Use a unique constraint on `(generated_question_draft_id, run_number)`, indexes for draft/run lookup, and a relationship that orders findings deterministically.

- [ ] **Step 3: Create the migration.**

  Use `0015_ai_generation_jobs` as `down_revision`. Create enum/check constraints and both tables with the same foreign-key and uniqueness semantics as the ORM models. The downgrade must remove findings before runs.

- [ ] **Step 4: Implement only enough persistence to pass the tests.**

  Keep models in the existing API model module and use the project’s UUID/timestamp conventions. Do not create a parallel validation database or JSON-only event store.

- [ ] **Step 5: Run focused tests.**

  Run:

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_curriculum_models.py apps/api/tests/test_question_validation_models.py -q
  ```

- [ ] **Step 6: Commit the persistence slice.**

  ```powershell
  git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0016_ai_question_validation_runs.py apps/api/tests/test_curriculum_models.py apps/api/tests/test_question_validation_models.py
  git commit -m "feat: persist ai question validation runs"
  ```

## Task 2: Implement deterministic verification service and M1/E1 checks

**Files:**

- Create: `apps/api/src/edu_grader_api/services/question_verification.py`
- Create: `apps/api/tests/test_question_verification.py`
- Modify: `apps/api/src/edu_grader_api/models.py` only if a small relationship or index is needed by the service tests

- [ ] **Step 1: Write failing service tests for generic rules.**

  Use persisted generation jobs/drafts and a fake grader. Test each stable code and status:

  - inactive curriculum revision -> `curriculum_revision_inactive` / blocked;
  - type outside the objective profile -> `question_type_not_allowed` / blocked;
  - invalid persisted policy -> `policy_schema_invalid` / blocked;
  - malformed or overlong prompt/explanation -> `prompt_or_explanation_invalid` / blocked;
  - same tenant, normalized duplicate prompt -> `duplicate_candidate_content` / warning;
  - explicit unsafe-minor category -> `unsafe_minor_content` / blocked;
  - unexpected internal validator exception -> `validator_unavailable` / blocked, without exception text in evidence.

- [ ] **Step 2: Implement generic rule helpers and a result value object.**

  Define small immutable input/result dataclasses rather than making route handlers decide validation status. Canonicalize duplicate text by Unicode-normalizing, case-folding, trimming, and collapsing whitespace. Compare only drafts belonging to the same tenant and exclude the draft being checked.

  Keep the minor-safety lexicon versioned and deliberately small for this slice. Store category identifiers such as `adult_content` in evidence, not the matched source text. Use the existing `validate_policy` call for policy correctness.

- [ ] **Step 3: Write failing M1 and E1 tests.**

  Verify that M1 requires a finite numeric expected answer and a finite non-negative tolerance, and that its grader probe must succeed. Verify that E1 requires a non-empty list of strings, normalized uniqueness, and bounded individual answers. Include a grade-text-complexity case that produces the non-blocking `grade_text_complexity_warning`.

- [ ] **Step 4: Implement M1/E1 checks using existing contracts.**

  For M1, reject booleans, NaN, infinity, missing values, and negative tolerance as `m1_answer_invalid`. Probe `HttpGraderClient.grade` with a canonical text answer only after local validation; convert an unsuccessful probe or client failure to `m1_grader_probe_failed`.

  For E1, canonicalize accepted answers before checking duplicate entries and length. Use a static, versioned grade-to-text-bound map keyed by the curriculum profile’s internal level; unknown grades must skip the warning rather than inventing a grade mapping. Never call the grader for E1.

- [ ] **Step 5: Persist a new immutable run for every invocation.**

  Query the next run ordinal transactionally, create a `GenerationValidationRun`, add one `ValidationFinding` per result, and derive status with this precedence:

  ```python
  if any(finding.severity is ValidationFindingSeverity.BLOCKED for finding in findings):
      status = ValidationRunStatus.BLOCKED
  elif findings:
      status = ValidationRunStatus.WARNING
  else:
      status = ValidationRunStatus.PASSED
  ```

  Wrap the orchestrator boundary so an unexpected exception produces a separately persisted `validator_unavailable` finding. Do not overwrite an earlier run and do not update a candidate draft’s acceptance state in this task.

- [ ] **Step 6: Run focused service tests.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py -q
  ```

- [ ] **Step 7: Commit the service slice.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py apps/api/src/edu_grader_api/models.py
  git commit -m "feat: verify ai question candidates"
  ```

## Task 3: Expose tenant-scoped trigger and read APIs

**Files:**

- Create: `apps/api/src/edu_grader_api/routers/ai_question_validation.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Create: `apps/api/tests/test_question_validation_api.py`
- Modify: `README.md` or the existing API documentation location, if it documents AI-generation endpoints

- [ ] **Step 1: Write failing API tests.**

  Cover a teacher/admin triggering validation for a draft in their tenant, tenant isolation returning the project’s stable not-found response, run retrieval, ordered run history, and a blocked result returned without raw internal diagnostics. Inject a fake verification service or fake grader so tests make no network calls.

- [ ] **Step 2: Add response schemas and routes.**

  Add exactly these routes:

  ```text
  POST /v1/ai-generated-questions/{draft_id}/validation-runs
  GET  /v1/ai-generated-questions/{draft_id}/validation-runs
  GET  /v1/ai-question-validation-runs/{run_id}
  ```

  The trigger route invokes the service and returns the persisted run. List responses are newest-first; a run response includes stable status, version metadata, findings, evidence, and remediation. Do not add mutable update/delete routes.

- [ ] **Step 3: Integrate authentication, tenancy, and audit logging.**

  Mirror the role dependency and tenant-scoped draft query used by the existing AI-generation router. Emit a safe audit event with draft ID, run ID, final status, and finding-code count; never write candidate prompt, answers, provider data, or exception text to the audit event.

- [ ] **Step 4: Document the API boundary.**

  Add a concise endpoint section that states runs are immutable, `warning` requires explicit teacher confirmation in the future acceptance flow, and `blocked` must not be accepted by that flow. Mark batch acceptance enforcement as deferred rather than implying these routes enforce it today.

- [ ] **Step 5: Run focused API tests.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_validation_api.py -q
  ```

- [ ] **Step 6: Commit the API slice.**

  ```powershell
  git add apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_question_validation_api.py README.md
  git commit -m "feat: expose question validation runs"
  ```

## Task 4: Verify the integrated slice and prepare review

**Files:**

- Modify only files identified by failures from this task’s verification commands.

- [ ] **Step 1: Run formatting and static checks on changed Python files.**

  ```powershell
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  ```

- [ ] **Step 2: Run the full project test suite with this worktree’s sources.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ```

- [ ] **Step 3: Inspect the migration chain and working tree.**

  ```powershell
  rg -n "revision|down_revision" apps/api/alembic/versions/0015_ai_generation_jobs.py apps/api/alembic/versions/0016_ai_question_validation_runs.py
  git status --short
  git log --oneline origin/main..HEAD
  ```

- [ ] **Step 4: Review scope and prepare the handoff.**

  Confirm that every result is draft-scoped and append-only, every failure code is stable, no route mutates acceptance state, no secret/raw exception is exposed, and deferred M2/E2-E4 and semantic validators are recorded as follow-up scope. Commit only failure-driven fixes, then push and open a PR for review.

## Verification checklist

- [ ] Persistence tests prove reruns are separate immutable records.
- [ ] Service tests cover all generic, M1, E1, warning, and safe-failure codes in this slice.
- [ ] API tests prove tenant isolation, role protection, immutable read paths, and safe response/audit metadata.
- [ ] Ruff and the full test suite pass using sources from this worktree.
- [ ] Migration revision chain reaches `0016_ai_question_validation_runs` from `0015_ai_generation_jobs`.
