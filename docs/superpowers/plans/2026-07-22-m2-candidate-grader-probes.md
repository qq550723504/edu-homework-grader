# M2 Candidate Grader-Probe Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every schema-valid M2@2 generated candidate with a fixed, safe set of existing-Grader answer probes before it can pass candidate validation.

**Architecture:** Core constructs five bounded raw MathJSON probe envelopes but never parses, evaluates, or normalizes a probe itself. `HttpGraderClient` forwards a deliberate null MathJSON value to the already-deployed Grader review path; the Core verifier validates only the Grader's stable decision and finite score, then appends one sanitized blocked finding when a probe does not match its contract.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, existing HTTP Grader adapter, existing Grader MathJSON/worker limits, pytest, Ruff.

## Global Constraints

- Apply only to valid M2 policy version `"2"`; keep M1 and non-M2 behavior unchanged.
- Reuse `VerificationGraderClient.grade` and the existing Grader for every answer decision; do not add Core MathJSON parsing, SymPy, `eval`, a solver, an endpoint, a migration, or a dependency.
- Keep the one existing expected-answer `normalize_math_answer` call before probes; never normalize a probe in Core.
- Probe IDs and order are exactly `expected_mathjson`, `one_unit_offset`, `empty_mathjson`, `zero_denominator`, `resource_limit`.
- Expected outcomes are: expected = `auto_accepted`/full finite score; offset = `auto_rejected`/zero finite score; the final three = `needs_review`/zero finite score.
- Continue through all five probes even after a failure, record only the first failure, and block with `m2_grader_probe_failed` evidence exactly `{"probe": "<id>"}`.
- Never persist prompt text, expected/probe MathJSON, AST, Grader evidence/feedback/version, or exception text in a finding/remediation.
- Preserve malformed expected behavior as `m2_mathjson_invalid`, fail closed on any exception/non-finite/unexpected response, and never create or mutate `QuestionVersion`.
- The `null` probe must cross the existing Core HTTP adapter to `/v1/grade/math/expression-v2`; it must not be locally interpreted as a pass.
- Semantic misconception inference and #42 calibration, plus #41 acknowledgement/publication behavior, are out of scope.

---

### Task 1: Preserve the Grader null-MathJSON review boundary

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/grader.py`
- Modify: `apps/api/tests/test_math_policy_v2.py`
- Modify: `services/grader/tests/test_mathjson.py`

**Interfaces:**

- `HttpGraderClient.grade("M2", rule_json, {"mathjson": None}, policy_version="2")` posts JSON with `student_mathjson: null` to `/v1/grade/math/expression-v2`.
- The existing Grader endpoint returns `needs_review` with score `0` for a null student expression and does not raise a transport/schema error.

- [ ] **Step 1: Add failing Core-adapter and Grader endpoint tests.**

  In `test_math_policy_v2.py`, mock `httpx.post`, grade an M2 rule with
  `{"mathjson": None}`, and assert the exact outgoing JSON keeps
  `"student_mathjson": None` rather than raising before the post. In
  `services/grader/tests/test_mathjson.py`, post the same null student value to
  `/v1/grade/math/expression-v2` and assert:

  ```python
  assert response.status_code == 200
  assert response.json()["decision"] == "needs_review"
  assert response.json()["score"] == 0
  ```

- [ ] **Step 2: Run the focused tests and confirm RED.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_math_policy_v2.py services/grader/tests/test_mathjson.py -k null -q
  ```

  Expected: the Core adapter test fails because `_mathjson_request` raises on
  `None`; the endpoint test establishes the current Grader review contract.

- [ ] **Step 3: Forward a present null MathJSON value without weakening rule validation.**

  Change `_mathjson_request` so it requires the `mathjson` key but permits its
  value to be `None`, then passes that value unchanged as `student_mathjson`.
  Keep the existing expected/variables/form/score checks and every non-M2
  envelope unchanged. Do not modify the Grader route: its `Any` input and
  `MathJsonValidationError` review result are already the authority.

- [ ] **Step 4: Run focused adapter/Grader tests and static checks.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_math_policy_v2.py services/grader/tests/test_mathjson.py -k "null or mathjson" -q
  ruff check apps/api/src/edu_grader_api/services/grader.py apps/api/tests/test_math_policy_v2.py services/grader/tests/test_mathjson.py
  ruff format --check apps/api/src/edu_grader_api/services/grader.py apps/api/tests/test_math_policy_v2.py services/grader/tests/test_mathjson.py
  git diff --check
  ```

- [ ] **Step 5: Commit Task 1.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/grader.py apps/api/tests/test_math_policy_v2.py services/grader/tests/test_mathjson.py
  git commit -m "fix: forward null M2 answers to grader"
  ```

### Task 2: Run deterministic M2 candidate answer probes

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- `_M2Probe(name: str, mathjson: object, decision: str, score_kind: Literal["full", "zero"])` represents an in-memory candidate verification probe.
- `_m2_probes(expected: object) -> tuple[_M2Probe, ...]` returns the five global-contract probes in their fixed order.
- `_m2_findings(...)` normalizes the expected expression once, then grades all five probes and returns one sanitized failure finding at most.

- [ ] **Step 1: Add RED tests for exact calls and outcomes.**

  Extend `PassingM2Grader` into a recording fixture that responds according to
  these probe answer envelopes. Assert that valid M2 verification calls the
  normalizer exactly once and grades these five student values in order:

  ```python
  expected = ["Add", "x", 1]
  assert [request[2]["mathjson"] for request in grader.grade_requests] == [
      expected,
      ["Add", expected, 1],
      None,
      ["Divide", 1, 0],
      _nested_negate_probe(depth=21),
  ]
  ```

  Add parameterized tests for an unexpected decision, non-finite score,
  wrong nonzero score, and an exception on each probe. Assert all five calls
  still occur, the first failure alone is `m2_grader_probe_failed`, evidence is
  exactly `{"probe": probe_id}`, and raw MathJSON/Grader diagnostics are absent
  from evidence and remediation. Cover a `required_form="expanded"` candidate
  to prove the expected-answer full-score requirement is retained.

- [ ] **Step 2: Run focused verifier tests and confirm RED.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k "m2 and (probe or full_score)" -q
  ```

  Expected: failures because `_m2_findings` currently grades only
  `expected_mathjson`.

- [ ] **Step 3: Add bounded probe construction and strict response checking.**

  Define `_M2Probe` beside `_M1Probe`. Build the nested negate tree iteratively
  with exactly 21 operators; do not inspect or transform `expected` beyond
  embedding it as an operand in `["Add", expected, 1]`. For each response,
  require a string decision and a finite numeric score; require `max_score` for
  the expected probe, exactly zero for every other probe, and the decision in
  the interface contract. Catch every injected-Grader exception as a failed
  probe, but continue iterating. Do not call `normalize_math_answer` again.

- [ ] **Step 4: Run focused and complete verifier checks.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k m2 -q
  python -m pytest tests/test_question_verification.py -q
  ruff check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  ruff format --check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  git diff --check
  ```

- [ ] **Step 5: Commit Task 2.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: probe M2 candidate answers with grader"
  ```

### Task 3: Record the delivery boundary and run cross-service regression

**Files:**

- Modify: `docs/ai-question-generation-plan.md`
- Modify: `docs/superpowers/specs/2026-07-22-m2-candidate-grader-probes-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-m2-candidate-grader-probes.md`

**Interfaces:**

- Documentation states that M2 candidate verification runs only deterministic
  Grader probes; it does not infer misconceptions, auto-publish, or replace
  #41/#42 work.

- [ ] **Step 1: Update the adoption boundary and completed checkboxes.**

  Add a compact M2 probe statement to `docs/ai-question-generation-plan.md`.
  Mark only completed spec and plan steps, and state that explicit curated
  misconception corpora remain #42 work rather than treating an offset probe as
  learner-behavior evidence.

- [ ] **Step 2: Run complete relevant verification.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests services/grader/src services/grader/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests services/grader/src services/grader/tests
  git diff --check
  ```

  Expected: all tests pass; only the established Alembic `path_separator`
  deprecation warning is allowed.

- [ ] **Step 3: Audit delivery boundaries.**

  Verify the final diff has no new parser/evaluator/dependency, no raw probe or
  candidate content in findings, no second expected normalizer call, no
  `QuestionVersion` mutation, no teacher acknowledgement/publication behavior,
  and no claim that a synthetic offset is a real common misconception.

- [ ] **Step 4: Commit Task 3.**

  ```powershell
  git add docs/ai-question-generation-plan.md docs/superpowers/specs/2026-07-22-m2-candidate-grader-probes-design.md docs/superpowers/plans/2026-07-22-m2-candidate-grader-probes.md
  git commit -m "docs: record M2 candidate probe boundary"
  ```

## Plan self-review

- **Spec coverage:** Task 1 preserves the real null-to-review adapter contract; Task 2 implements all five deterministic candidate probes, ordering, fail-closed result checks, and no-leak persistence; Task 3 documents the scope and verifies the cross-service boundary.
- **Placeholder scan:** Every task lists exact files, names, probe values, response contracts, test assertions, commands, and commit scope. No implementation is deferred behind a placeholder.
- **Type consistency:** Task 1 keeps `grade(..., answer_json: dict[str, object])`; Task 2's probes supply the same `{"mathjson": object}` envelope to it and return existing `VerificationFinding` objects; Task 3 documents those same public boundaries.
