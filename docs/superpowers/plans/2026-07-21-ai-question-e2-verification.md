# E2 Candidate Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Verify every E2@1 accepted word form with the existing English Grader before a candidate can pass.

**Architecture:** Add an E2 helper to `question_verification.py`, gated behind successful common policy validation. It normalizes configured forms, probes each with a `text-v1` answer envelope, and emits only stable sanitized findings through the existing immutable validation-run path.

**Tech Stack:** Python 3.12+, existing API verification service and English Grader protocol, pytest, Ruff.

## Global Constraints

- Reuse the existing English Grader; add no dictionary, lemmatizer, LLM, or LanguageTool call.
- Run E2-specific checks only for schema-valid E2@1 candidates.
- Never include a form, lemma, exception message, or grader payload in finding evidence.
- Never create or mutate a `QuestionVersion`.

### Task 1: Add E2 form and Grader probes

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:** Add `_e2_findings(rule_json: dict[str, object], policy_version: object, grader_client: VerificationGraderClient) -> list[VerificationFinding]`.

- [x] **Step 1: Write failing E2 tests.**

  Add an E2@1 candidate with lemma `go`, accepted form `went`, and tense constraint `past`. Assert a fake English Grader receiving `{"format": "text-v1", "text": "went"}` makes the run pass. Add normalized duplicate forms and a fake rejected/failed probe; assert `e2_forms_invalid` or `e2_grader_probe_failed` with evidence `{"probe": "accepted_forms"}`.

- [x] **Step 2: Run the E2 tests and verify failure.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py -k e2 -q
  ```

  Expected: FAIL because E2 has no type-specific verifier.

- [x] **Step 3: Implement the minimal helper.**

  ```python
  if question_type == "E2" and isinstance(rule_json, dict) and not policy_errors:
      findings.extend(_e2_findings(rule_json, policy_version, grader_client))

  def _e2_findings(rule_json, policy_version, grader_client):
      if policy_version != "1":
          return []
      forms = rule_json["accepted_forms"]
      if len({_normalize_text(form) for form in forms}) != len(forms):
          return [_blocked("e2_forms_invalid", {"reason": "normalized_duplicate"}, "Remove duplicate accepted forms.")]
      for form in forms:
          result = grader_client.grade("E2", rule_json, {"format": "text-v1", "text": form}, policy_version="1")
          if result.decision != "auto_accepted" or not math.isclose(result.score, float(rule_json.get("max_score", 1)), rel_tol=0, abs_tol=1e-9):
              return [_blocked("e2_grader_probe_failed", {"probe": "accepted_forms"}, "Correct the E2 forms or constraints.")]
      return []
  ```

  Convert any Grader exception to `e2_grader_probe_failed` with the same evidence.

- [x] **Step 4: Re-run focused E2 tests.**

  ```powershell
  python -m pytest apps/api/tests/test_question_verification.py -k e2 -q
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify E2 candidate forms"
  ```

### Task 2: Verify and publish

- [x] **Step 1: Run full project checks.**

  ```powershell
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ```

- [x] **Step 2: Confirm scope.** Invalid E2 rules retain `policy_schema_invalid` without calling the Grader; E2 evidence is sanitized, and this slice adds no external dependency or `QuestionVersion` mutation.

- [ ] **Step 3: Push and open a PR.**

  ```powershell
  git push -u origin codex/ai-question-e2-verification
  gh pr create --base main --head codex/ai-question-e2-verification --title "feat: verify E2 candidate forms"
  ```
