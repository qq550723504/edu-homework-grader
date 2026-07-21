# M2 Candidate Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, draft-scoped M2@2 MathJSON normalization and Grader probes to AI candidate verification runs.

**Architecture:** Extend the existing `question_verification` service with an M2-specific helper that depends only on the injected verification grader protocol. The helper normalizes the configured expected MathJSON with declared variables, then probes the existing M2 grading path using the expected expression. It emits only stable, sanitized blocked findings and uses the existing immutable-run persistence path.

**Tech Stack:** Python 3.12+, SQLAlchemy 2, FastAPI service layer, existing `HttpGraderClient`, existing Grader MathJSON normalizer, pytest, Ruff.

## Global Constraints

- Reuse `normalize_math_answer` and `grade`; do not add a MathJSON parser, symbolic evaluator, or `eval` path.
- Only M2 policy version `2` receives a type-specific probe; common policy validation remains the gate for all other versions.
- Findings must not contain a raw MathJSON expression, raw exception message, provider response, or learner data.
- Every call appends an immutable draft-scoped validation run and never creates or changes `QuestionVersion`.

### Task 1: Extend the verification grader interface and add M2 regression tests

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Extend `VerificationGraderClient` with `normalize_math_answer(answer_json: dict[str, object]) -> dict[str, object]`.
- Add `_m2_findings(rule_json: dict[str, object], policy_version: object, grader_client: VerificationGraderClient) -> list[VerificationFinding]`.

- [ ] **Step 1: Add failing M2 success and normalization tests.**

  Add a fake M2 client that returns a safe AST and a full-score `GradeResult`. Create a candidate with `question_type="M2"`, `policy_version="2"`, `expected=["Add", "x", 1]`, `variables=["x"]`, `required_form="expanded"`, and `max_score=1`. Assert the appended run is `passed` and the normalizer receives only the expected MathJSON and declared variables.

  ```python
  def test_valid_m2_candidate_normalizes_and_probes(session: Session) -> None:
      draft = generation_draft(session, candidate_json=valid_m2_candidate())
      grader = PassingM2Grader()

      run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

      assert run.status is ValidationRunStatus.PASSED
      assert grader.normalization_requests == [{"mathjson": ["Add", "x", 1], "variables": ["x"]}]
      assert grader.grade_requests[0][0] == "M2"
  ```

- [ ] **Step 2: Run the focused test and verify it fails.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py::test_valid_m2_candidate_normalizes_and_probes -q
  ```

  Expected: FAIL because the verification protocol has no normalizer and the M2 helper is absent.

- [ ] **Step 3: Implement the minimal successful M2 probe.**

  ```python
  if question_type == "M2" and isinstance(rule_json, dict):
      findings.extend(_m2_findings(rule_json, policy_version, grader_client))

  def _m2_findings(
      rule_json: dict[str, object],
      policy_version: object,
      grader_client: VerificationGraderClient,
  ) -> list[VerificationFinding]:
      if policy_version != "2":
          return []
      expected = rule_json["expected"]
      variables = rule_json.get("variables", [])
      grader_client.normalize_math_answer({"mathjson": expected, "variables": variables})
      result = grader_client.grade(
          "M2", rule_json, {"mathjson": expected}, policy_version="2"
      )
      if result.score < float(rule_json.get("max_score", 1)):
          return [_blocked(
              "m2_grader_probe_failed",
              {"probe": "expected_mathjson"},
              "Correct the M2 rule so the expected expression receives full credit.",
          )]
      return []
  ```

  Require a successful decision (`auto_accepted` or `correct`) and a score equal to `max_score`; do not persist normalizer output.

- [ ] **Step 4: Re-run the focused test and verify it passes.**

  Run the Step 2 command. Expected: PASS.

### Task 2: Block unsafe MathJSON and failed probes without sensitive evidence

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- `m2_mathjson_invalid` is a blocked finding with evidence `{"probe": "expected_mathjson"}`.
- `m2_grader_probe_failed` is a blocked finding with evidence `{"probe": "expected_mathjson"}`.

- [ ] **Step 1: Add failing safety tests.**

  Use fakes that raise from `normalize_math_answer`, raise from `grade`, and return a rejected or partial-score result. Assert the run is blocked, has the expected stable code, and evidence/remediation do not contain the expression or exception text.

  ```python
  def test_m2_normalizer_failure_is_safely_blocked(session: Session) -> None:
      draft = generation_draft(session, candidate_json=valid_m2_candidate())
      run = verification.run_candidate_verification(session, draft=draft, grader_client=FailingM2Normalizer())

      finding = next(item for item in run.findings if item.code == "m2_mathjson_invalid")
      assert run.status is ValidationRunStatus.BLOCKED
      assert finding.evidence_json == {"probe": "expected_mathjson"}
  ```

- [ ] **Step 2: Run focused M2 tests and verify they fail.**

  ```powershell
  python -m pytest apps/api/tests/test_question_verification.py -k m2 -q
  ```

  Expected: FAIL because normalizer and grader failures are not yet converted into M2 findings.

- [ ] **Step 3: Convert dependency failures to sanitized findings.**

  Wrap normalizer failures separately from grading failures:

  ```python
  try:
      grader_client.normalize_math_answer({"mathjson": expected, "variables": variables})
  except Exception:
      return [_blocked("m2_mathjson_invalid", {"probe": "expected_mathjson"},
                       "Correct the expected MathJSON expression and variables.")]
  ```

  Use `m2_grader_probe_failed` for a grading exception, unsupported result decision, or score different from `max_score`.

- [ ] **Step 4: Re-run focused M2 tests and verify they pass.**

  Run the Step 2 command. Expected: PASS.

- [ ] **Step 5: Commit the M2 service slice.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify M2 candidate expressions"
  ```

### Task 3: Verify integration and prepare review

**Files:**

- Modify only files identified by verification failures.

- [ ] **Step 1: Run the verification service and API tests.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py -q
  ```

- [ ] **Step 2: Run project checks.**

  ```powershell
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ```

- [ ] **Step 3: Review the scope before publishing.**

  Confirm the implementation reuses the existing Grader, has no `eval` or parser addition, writes no raw MathJSON to findings, keeps M2@1 on common schema-only validation, and does not create or mutate `QuestionVersion`.

- [ ] **Step 4: Push and open a PR.**

  ```powershell
  git push -u origin codex/ai-question-m2-verification
  gh pr create --base main --head codex/ai-question-m2-verification --title "feat: verify M2 candidate expressions"
  ```
