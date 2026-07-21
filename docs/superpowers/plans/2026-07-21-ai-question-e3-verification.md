# E3 Candidate Grammar Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify E3@1 candidate prompts and reference answers through the existing Grader/LanguageTool path without weakening teacher review or persisting raw grammar feedback.

**Architecture:** Add a schema-gated `_e3_findings` helper to the API verification service. It makes an in-memory copy of the E3 rule with grammar feedback forced on, probes the prompt and each optional accepted answer through `VerificationGraderClient`, and reduces every successful response to a count. Grammar matches become sanitized warnings; dependency, response-shape, or decision failures become sanitized blocked findings.

**Tech Stack:** Python 3.14, existing Core API verification service, existing Grader E3 endpoint and private LanguageTool adapter, pytest, Ruff.

## Global Constraints

- Support only E3@1 candidates whose common `validate_policy` check has already passed.
- Reuse `VerificationGraderClient.grade`; do not create an API-side LanguageTool client or dependency.
- Probe the prompt and each configured `accepted_answers` value with `{"format": "text-v1", "text": value}`.
- Force `grammar_feedback_required=True` only in an in-memory probe rule; never mutate `draft.candidate_json` or `rule_json`.
- Require `decision == "needs_review"` and an evidence `feedback` list whose elements are objects; persist only counts, never the response body.
- Persist `e3_grammar_warning` as warning and `e3_grammar_probe_failed` as blocked with the exact sanitized evidence in the approved design.
- Do not create a `QuestionVersion`, alter E3 publication/review rules, add a migration, or modify E4 behavior.

---

### Task 1: Add E3 grammar-probe verification

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Produces `_e3_findings(rule_json: dict[str, object], policy_version: object, prompt: str, grader_client: VerificationGraderClient) -> list[VerificationFinding]`.
- Produces `_e3_feedback_count(result: GradeResult) -> int`, which raises `ValueError` when the response is not the expected E3 review envelope.
- Consumes the existing `GradeResult.decision` and `GradeResult.evidence` contract from `apps/api/src/edu_grader_api/services/questions.py`.

- [x] **Step 1: Write failing E3 tests.**

  Add a fake Grader that records requests and returns a review-only response with configurable feedback:

  ```python
  class PassingE3Grader(PassingGrader):
      def __init__(self, feedback: list[object] | None = None) -> None:
          self.feedback = feedback or []
          self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

      def grade(self, question_type, rule_json, answer_json, *, policy_version=None) -> GradeResult:
          self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
          return GradeResult("needs_review", 0, {"feedback": self.feedback}, "fake-e3-v1")
  ```

  Add `valid_e3_candidate()` with `question_type="E3"`, `policy_version="1"`, a prompt, `grammar_feedback_required=False`, and two `accepted_answers`. Test all of the following:

  ```python
  def test_valid_e3_candidate_probes_prompt_and_reference_answers(session):
      draft = generation_draft(session, allowed_question_types=["E3"], candidate_json=valid_e3_candidate())
      grader = PassingE3Grader()
      run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

      assert run.status is ValidationRunStatus.PASSED
      assert [request[2]["text"] for request in grader.grade_requests] == [
          draft.candidate_json["prompt"], "went", "travelled"
      ]
      assert all(request[1]["grammar_feedback_required"] is True for request in grader.grade_requests)
      assert draft.candidate_json["rule_json"]["grammar_feedback_required"] is False
  ```

  Add a feedback fake with two object items and assert warnings have exactly:

  ```python
  {"target": "prompt", "grammar_match_count": 2, "reference_answer_count": 2}
  {"target": "reference_answers", "grammar_match_count": 2, "reference_answer_count": 2}
  ```

  Add parametrized failure fakes for a raised exception, `auto_accepted` decision, and `{"feedback": ["not-an-object"]}`. Assert one `e3_grammar_probe_failed` finding with `{"target": "prompt", "reference_answer_count": 2}` and confirm its remediation does not contain candidate text or the exception text. Add an invalid E3 rule missing `grammar_feedback_required`; assert `policy_schema_invalid` and zero Grader calls.

- [x] **Step 2: Run the focused tests and confirm they fail.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py -k e3 -q
  ```

  Expected: FAIL because E3 has no candidate-specific probe helper.

- [x] **Step 3: Implement the minimal schema-gated helper.**

  Add the E3 call beside the existing M2/E2 calls, preserving the common policy gate:

  ```python
  if question_type == "E3" and isinstance(rule_json, dict) and not policy_errors:
      findings.extend(_e3_findings(rule_json, policy_version, prompt, grader_client))
  ```

  Add these helpers in `question_verification.py`:

  ```python
  def _e3_findings(
      rule_json: dict[str, object],
      policy_version: object,
      prompt: str,
      grader_client: VerificationGraderClient,
  ) -> list[VerificationFinding]:
      if policy_version != "1":
          return []
      accepted_answers = rule_json.get("accepted_answers", [])
      if not isinstance(accepted_answers, list) or not all(isinstance(answer, str) for answer in accepted_answers):
          return [_blocked("e3_grammar_probe_failed", {"target": "prompt", "reference_answer_count": 0}, "Retry validation after the grammar checker is available.")]
      probe_rule = {**rule_json, "grammar_feedback_required": True}
      findings: list[VerificationFinding] = []
      probes = [("prompt", prompt), *(("reference_answers", answer) for answer in accepted_answers)]
      for target, text in probes:
          try:
              result = grader_client.grade("E3", probe_rule, {"format": "text-v1", "text": text}, policy_version="1")
              match_count = _e3_feedback_count(result)
          except Exception:
              return [*findings, _blocked("e3_grammar_probe_failed", {"target": target, "reference_answer_count": len(accepted_answers)}, "Retry validation after the grammar checker is available.")]
          if match_count:
              findings.append(VerificationFinding("e3_grammar_warning", ValidationFindingSeverity.WARNING, {"target": target, "grammar_match_count": match_count, "reference_answer_count": len(accepted_answers)}, "Revise the generated language before teacher review."))
      return findings


  def _e3_feedback_count(result: GradeResult) -> int:
      feedback = result.evidence.get("feedback")
      if result.decision != "needs_review" or not isinstance(feedback, list) or not all(isinstance(item, dict) for item in feedback):
          raise ValueError("unexpected E3 grammar response")
      return len(feedback)
  ```

  Keep remediation strings free of prompt text, reference answers, LanguageTool feedback, and exception details. Do not store `result.evidence` itself.

- [x] **Step 4: Run focused tests and format the changed files.**

  ```powershell
  python -m pytest apps/api/tests/test_question_verification.py -k e3 -q
  ruff check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ruff format apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ruff format --check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ```

  Expected: focused E3 tests pass; Ruff reports no violations and both files are formatted.

- [x] **Step 5: Commit the implementation and focused tests.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify E3 candidate grammar"
  ```

### Task 2: Verify scope and publish the reviewable change

**Files:**

- Modify: `docs/superpowers/plans/2026-07-21-ai-question-e3-verification.md`
- Verify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Verify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Confirms the E3 helper uses the existing `VerificationGraderClient` boundary and emits only the approved sanitized finding evidence.
- Produces a reviewed pull request against `main`.

- [x] **Step 1: Run the complete regression and static-check suite.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  git diff --check
  ```

  Expected: all tests pass; Ruff and whitespace checks succeed. Treat only the known Alembic `path_separator` deprecation warning as non-blocking.

- [x] **Step 2: Confirm the delivery boundary.**

  Inspect the diff and verify all of these facts:

  - E3 helpers run only after `policy_errors` is empty.
  - Every probe rule is copied before forcing grammar feedback.
  - No finding evidence includes probe text, feedback, offsets, rule IDs, replacements, signals, or exception messages.
  - Grammar feedback creates warning, while a dependency or envelope failure creates blocked.
  - There is no LanguageTool import or HTTP call in `apps/api` and no `QuestionVersion` mutation.

- [x] **Step 3: Record completion and open a pull request.**

  Mark the executed plan steps as complete, then run:

  ```powershell
  git add docs/superpowers/plans/2026-07-21-ai-question-e3-verification.md
  git commit -m "docs: record E3 verification delivery"
  git push -u origin codex/ai-question-e3-verification
  gh pr create --base main --head codex/ai-question-e3-verification --title "feat: verify E3 candidate grammar"
  ```

  Expected: the PR contains only the E3 candidate-verification implementation, its tests, and the E3 design/plan documents.

## Plan Self-Review

- **Spec coverage:** Task 1 implements schema gating, in-memory grammar enablement, prompt/reference probes, sanitized warning and blocked outcomes, no raw evidence persistence, and review-only behavior. Task 2 verifies all forbidden-boundary constraints and publishes the reviewed delivery.
- **Placeholder scan:** Every task names exact files, interfaces, test cases, commands, expected results, and commit scopes. No deferred implementation or unspecified error handling remains.
- **Type consistency:** `_e3_findings` consumes the existing `VerificationGraderClient` and `GradeResult` contracts; `_e3_feedback_count` returns an `int` used only as sanitized count evidence.
