# M1 Candidate Numeric-Probe Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every schema-valid M1@1 candidate prove through the existing Grader that its expected answer and tolerance boundaries accept correctly while empty and outside answers reject.

**Architecture:** Extend the existing M1 verification helper with private immutable probe metadata and Decimal-only text construction. The helper sends six bounded `text-v1` answers through `VerificationGraderClient.grade`, checks only the returned decision/score contract, and emits the existing sanitized blocked findings. The database, routing, Grader implementation and publication path remain unchanged.

**Tech Stack:** Python 3.14, standard-library `dataclasses`, `decimal`, `math`, existing Core API verification service and injected Grader client, pytest, Ruff.

## Global Constraints

- Run type-specific probes only for schema-valid M1 policy version `"1"`; invalid policy fields retain `policy_schema_invalid` and make no type-specific Grader call.
- Reuse `VerificationGraderClient.grade("M1", rule_json, {"format": "text-v1", "text": answer}, policy_version="1")`; do not add an evaluator, parser, `eval`, HTTP route or Grader change.
- Construct text with `Decimal(str(expected))` and `Decimal(str(tolerance))` only; Core must never decide whether a learner answer is correct.
- Probe exactly `expected_answer`, `empty_answer`, `lower_tolerance_boundary`, `upper_tolerance_boundary`, `below_tolerance_boundary`, and `above_tolerance_boundary`, in that order.
- Accepted probes require finite score `> 0` and `decision == "auto_accepted"`; rejected probes require finite score `== 0` and `decision == "auto_rejected"`.
- Evidence is exactly `{"probe": probe_id}` for Grader failures and contains no answer, tolerance, score, response, exception, prompt, or learner data.
- Preserve `m1_answer_invalid` for invalid inputs and use `{"reason": "probe_construction"}` if safe bounded probe construction fails.
- Every validation result remains append-only and draft-scoped; do not mutate a candidate or create/change a `QuestionVersion`.
- This slice does not claim prompt-specific misconceptions, curriculum golden corpus coverage, #42 evaluation, or M1 error-rate calibration.

---

### Task 1: Add deterministic M1 probe construction and Grader-contract tests

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Produces `_M1Probe(name: str, text: str, expects_acceptance: bool)` as a private frozen dataclass.
- Produces `_m1_probes(expected: int | float, tolerance: int | float) -> tuple[_M1Probe, ...]`.
- Updates `_m1_findings(rule_json: dict[str, object], policy_version: object, grader_client: VerificationGraderClient) -> list[VerificationFinding]`.
- Consumes the existing `GradeResult` and `VerificationGraderClient.grade` interfaces without changing their signatures.

- [x] **Step 1: Write failing M1 probe tests.**

  Add a `RecordingM1Grader` fake that records all calls and returns an injected `GradeResult` per answer text. It must return accepted positive-score results for expected/boundary probe answers and rejected zero-score results for blank/outside probes.

  Update any shared `PassingGrader` fixture exercised by ordinary M1 verification tests so its M1 responses faithfully model the production numeric contract for empty, expected, boundary and outside probe texts. This prevents the fixture's former unconditional acceptance from creating false regressions; production code must still delegate every verdict to the real injected Grader client.

  Add a valid M1 candidate with `expected=2.5`, `tolerance=0.25`. Assert the verifier performs exactly these calls in order and passes:

  ```python
  assert [request[2]["text"] for request in grader.grade_requests] == [
      "2.5", "", "2.25", "2.75", "1.25", "3.75"
  ]
  assert all(request[0] == "M1" and request[3] == "1" for request in grader.grade_requests)
  assert run.status is ValidationRunStatus.PASSED
  ```

  Add a zero-tolerance candidate and assert it retains both boundary probes (`"4"`, `"4"`) and outside probes (`"3"`, `"5"`). Add a negative expected/tolerance fixture such as `expected=-3`, `tolerance=0.5` and assert safe Decimal text `"-3.5"`, `"-2.5"`, `"-4.5"`, `"-1.5"`.

  Parametrize each probe ID with a fake result that violates its required contract: expected/boundary probes rejected or zero score; empty/outside probes accepted or positive score; any probe non-finite score; and a raised exception. Assert the run is blocked with exactly:

  ```python
  {"probe": probe_id}
  ```

  and assert evidence/remediation do not contain the candidate answer, tolerance, fake Grader evidence, or exception text. Add schema-invalid M1 (`policy_version="1"`, `expected="four"`) and non-`"1"` policy-version cases; assert zero type-specific Grader calls.

- [x] **Step 2: Run focused M1 tests and confirm they fail.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k m1 -q
  ```

  Expected: FAIL because current `_m1_findings` makes only the expected-answer call and does not construct boundary/empty/outside probes.

- [x] **Step 3: Implement bounded probe construction and result checks.**

  Import `Decimal` and `InvalidOperation`, then add the private immutable probe contract:

  ```python
  @dataclass(frozen=True)
  class _M1Probe:
      name: str
      text: str
      expects_acceptance: bool


  def _m1_probes(expected: int | float, tolerance: int | float) -> tuple[_M1Probe, ...]:
      expected_decimal = Decimal(str(expected))
      tolerance_decimal = Decimal(str(tolerance))
      values = (
          ("expected_answer", Decimal(str(expected)), True),
          ("empty_answer", None, False),
          ("lower_tolerance_boundary", expected_decimal - tolerance_decimal, True),
          ("upper_tolerance_boundary", expected_decimal + tolerance_decimal, True),
          ("below_tolerance_boundary", expected_decimal - tolerance_decimal - Decimal(1), False),
          ("above_tolerance_boundary", expected_decimal + tolerance_decimal + Decimal(1), False),
      )
      probes = tuple(
          _M1Probe(name, "" if value is None else str(value.normalize()), accepts)
          for name, value, accepts in values
      )
      if any(len(probe.text) > 100 for probe in probes):
          raise ValueError("M1 probe exceeds the numeric answer envelope")
      return probes
  ```

  Handle zero formatting explicitly so decimal zero becomes `"0"`, and reject a non-finite Decimal or failed conversion with `ValueError`. In `_m1_findings`, retain the existing finite/non-negative type guard; return `m1_answer_invalid` with `{"reason": "probe_construction"}` if `_m1_probes` raises. For each probe invoke the existing Grader boundary and require:

  ```python
  score_is_finite = isinstance(result.score, int | float) and math.isfinite(result.score)
  result_is_expected = (
      result.decision == "auto_accepted" and result.score > 0
      if probe.expects_acceptance
      else result.decision == "auto_rejected" and result.score == 0
  )
  ```

  On an exception, non-finite score, or unexpected result, return one `_blocked("m1_grader_probe_failed", {"probe": probe.name}, remediation)` finding. Keep the remediation free of probe text or diagnostic content.

- [x] **Step 4: Run focused tests and formatting.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k m1 -q
  ruff check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  ruff format src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  ruff format --check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  ```

  Expected: every M1 contract and leak-prevention test passes; Ruff has no violations.

- [x] **Step 5: Commit the M1 probe slice.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify M1 candidate numeric probes"
  ```

### Task 2: Document the M1 boundary and validate the reviewable branch

**Files:**

- Modify: `docs/ai-question-generation-plan.md`
- Modify: `docs/superpowers/specs/2026-07-22-m1-candidate-probes-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-m1-candidate-probes.md`
- Verify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Verify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Documents six deterministic M1 Grader probes, fail-closed contract behavior, and deferred #42/common-misconception work.
- Produces a tested branch ready for controller-owned full-branch review and PR creation.

- [x] **Step 1: Update the AI generation plan.**

  Add a compact M1 verification statement: schema-valid M1 candidates use the existing numeric Grader for correct, empty, inclusive-boundary and outside-boundary probes; unexpected dependency/result behavior blocks; persisted evidence identifies only the probe. State that prompt-specific misconception distractors and the golden corpus remain #40/#42 follow-up work.

- [x] **Step 2: Run complete relevant regression and static verification.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  git diff --check
  ```

  Expected: all tests, Ruff and whitespace checks pass. Treat only the established Alembic `path_separator` deprecation warning as non-blocking.

- [x] **Step 3: Perform the delivery boundary audit.**

  Verify all of the following against the final diff:

  - no local numeric acceptance/rejection verdict exists; every probe result comes from `VerificationGraderClient.grade`;
  - M1 invokes exactly six probes in stable order and preserves `text-v1` plus policy version `"1"`;
  - a failure stores only stable probe metadata, never numeric values, tolerance, score, Grader evidence, feedback, exceptions, prompt or learner data;
  - invalid schema or unsupported M1 policy version makes no type-specific call;
  - no Grader endpoint, provider, migration, `QuestionVersion`, routing, or #42 evaluation behaviour was added;
  - documentation explicitly distinguishes per-candidate probes from curriculum-specific misconception/golden-set work.

- [x] **Step 4: Commit documentation and hand off for branch review.**

  ```powershell
  git add docs/ai-question-generation-plan.md docs/superpowers/specs/2026-07-22-m1-candidate-probes-design.md docs/superpowers/plans/2026-07-22-m1-candidate-probes.md
  git commit -m "docs: record M1 probe verification delivery"
  ```

  Mark only completed implementation/validation plan checkboxes. Leave branch-review, push and PR bookkeeping controller-owned until final review is clean.

## Plan Self-Review

- **Spec coverage:** Task 1 implements every approved correct/empty/boundary/outside probe, stable result contract, safe construction and fail-closed evidence behavior. Task 2 documents exact scope, verifies the full monorepo surface and checks the delivery boundary.
- **Placeholder scan:** Every task specifies exact files, interfaces, probe names, evidence shape, test behavior, commands and commit scopes. No deferred implementation or unspecified safety behavior remains.
- **Type consistency:** `_M1Probe` supplies names/text/expected acceptance to `_m1_findings`; `VerificationGraderClient.grade` and `GradeResult` are existing unchanged contracts; all persisted failure evidence uses the same `{"probe": probe.name}` mapping.
