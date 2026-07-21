# E4 Candidate Scoring-Point Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Block internally inconsistent E4@2 candidate rubrics and evidence phrases that cannot earn their configured isolated scoring point through the existing review-only Grader.

**Architecture:** Add a schema-gated E4 helper to the API verification service. It checks normalized rubric uniqueness and total score deterministically, then probes every evidence phrase using an in-memory rule containing only its owning scoring point. All E4 probe responses must stay `needs_review` and earn exactly that isolated point score; only sanitized counts and numeric totals persist.

**Tech Stack:** Python 3.14, existing Core API verification service, existing E4 Grader/similarity adapter, pytest, Ruff.

## Global Constraints

- Support only E4@2 candidates that passed common `validate_policy` checks.
- Reuse `VerificationGraderClient.grade`; do not import a similarity model, call a processor directly, or add a dependency.
- Preserve `rule_json` and draft state: isolated probe rules are in-memory copies only.
- Require `decision == "needs_review"` and a finite score matching the single point score by `math.isclose(rel_tol=0, abs_tol=1e-9)`.
- Persist only approved codes and non-content evidence: counts, numeric totals, and stable categories; never IDs, phrases, prompt text, criteria, feedback, signals, model metadata, similarity values, or exceptions.
- Keep E4 teacher-review and publication behavior unchanged. Do not add a migration or `QuestionVersion` mutation.

---

### Task 1: Add E4 rubric integrity and isolated-Grader probes

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Produces `_e4_findings(rule_json: dict[str, object], policy_version: object, grader_client: VerificationGraderClient) -> list[VerificationFinding]`.
- Produces `_e4_probe_rule(rule_json: dict[str, object], point: dict[str, object], point_score: float) -> dict[str, object]`.
- Consumes the existing `GradeResult` contract and `VerificationGraderClient.grade` interface.

- [x] **Step 1: Write failing E4 tests.**

  Add a two-point E4@2 candidate:

  ```python
  def valid_e4_candidate() -> dict[str, object]:
      return {
          "question_type": "E4",
          "policy_version": "2",
          "prompt": "Read the short passage and answer in one sentence.",
          "rule_json": {
              "max_score": 3,
              "scoring_points": [
                  {"id": "reason", "evidence_phrases": ["because the bridge was closed"], "score": 2},
                  {"id": "result", "evidence_phrases": ["they arrived late"], "score": 1},
              ],
          },
          "explanation": "Identify both the cause and the result.",
      }
  ```

  Add a `PassingE4Grader` that records its calls and derives the returned score from the one point in `rule_json`:

  ```python
  class PassingE4Grader(PassingGrader):
      def __init__(self) -> None:
          self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

      def grade(self, question_type, rule_json, answer_json, *, policy_version=None) -> GradeResult:
          self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
          point = rule_json["scoring_points"][0]
          return GradeResult("needs_review", point["score"], {}, "fake-e4-v1")
  ```

  Add focused assertions for:

  ```python
  def test_valid_e4_candidate_probes_every_evidence_phrase(session):
      draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=valid_e4_candidate())
      grader = PassingE4Grader()
      run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

      assert run.status is ValidationRunStatus.PASSED
      assert [request[2]["text"] for request in grader.grade_requests] == [
          "because the bridge was closed", "they arrived late"
      ]
      assert [request[1]["max_score"] for request in grader.grade_requests] == [2.0, 1.0]
      assert all(len(request[1]["scoring_points"]) == 1 for request in grader.grade_requests)
      assert draft.candidate_json["rule_json"]["scoring_points"][0]["score"] == 2
  ```

  Add separate tests for normalized duplicate IDs, normalized duplicate phrases, and an unequal score total. Assert `e4_scoring_points_invalid` or `e4_score_total_invalid`, sanitized count/number evidence, and no Grader calls. Add a floating-point-valid total such as scores `0.7` and `0.2` with `max_score=0.9` and assert it passes deterministic validation.

  Add parametrized fakes returning a thrown exception, `auto_accepted`, partial score, and `float("nan")`; assert `e4_grader_probe_failed` is blocked with exactly `{"probe": "evidence_phrases", "scoring_point_count": 2, "evidence_phrase_count": 2}` and never contains phrase text or exception text. Add separate `NaN` point-score and `NaN` maximum-score candidates; assert `e4_score_total_invalid` with `{"reason": "non_finite_score", "scoring_point_count": 2, "evidence_phrase_count": 2}` and zero Grader calls. Add a malformed E4 rule missing `scoring_points`; assert `policy_schema_invalid` and no Grader calls.

- [x] **Step 2: Run focused E4 tests and confirm failure.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest apps/api/tests/test_question_verification.py -k e4 -q
  ```

  Expected: FAIL because the candidate verifier has no E4-specific helper or probes.

- [x] **Step 3: Implement the minimal E4 helper.**

  Add the guarded E4 call beside the existing type-specific helpers:

  ```python
  if question_type == "E4" and isinstance(rule_json, dict) and not policy_errors:
      findings.extend(_e4_findings(rule_json, policy_version, grader_client))
  ```

  Add a helper that follows this exact flow:

  ```python
  def _e4_findings(rule_json, policy_version, grader_client):
      if policy_version != "2":
          return []
      points = rule_json.get("scoring_points")
      if not isinstance(points, list):
          return []
      point_count = len(points)
      phrases = [phrase for point in points for phrase in point["evidence_phrases"]]
      if _has_normalized_duplicates([point["id"] for point in points]):
          return [_blocked("e4_scoring_points_invalid", {"reason": "normalized_duplicate_id", "scoring_point_count": point_count, "evidence_phrase_count": len(phrases)}, "Use distinct scoring-point identifiers.")]
      if _has_normalized_duplicates(phrases):
          return [_blocked("e4_scoring_points_invalid", {"reason": "normalized_duplicate_phrase", "scoring_point_count": point_count, "evidence_phrase_count": len(phrases)}, "Use distinct evidence phrases across scoring points.")]
      max_score = float(rule_json.get("max_score", 1))
      total = sum(float(point["score"]) for point in points)
      if not math.isclose(total, max_score, rel_tol=0, abs_tol=1e-9):
          return [_blocked("e4_score_total_invalid", {"scoring_point_count": point_count, "point_score_total": total, "max_score": max_score}, "Make the scoring-point total equal the rubric maximum score.")]
      for point in points:
          score = float(point["score"])
          probe_rule = _e4_probe_rule(rule_json, point, score)
          for phrase in point["evidence_phrases"]:
              try:
                  result = grader_client.grade("E4", probe_rule, {"format": "text-v1", "text": phrase}, policy_version="2")
              except Exception:
                  return [_e4_probe_failure(point_count, len(phrases))]
              if result.decision != "needs_review" or not _is_finite_number(result.score) or not math.isclose(result.score, score, rel_tol=0, abs_tol=1e-9):
                  return [_e4_probe_failure(point_count, len(phrases))]
      return []
  ```

  Implement `_e4_probe_rule` as `{**rule_json, "scoring_points": [point], "max_score": point_score}`. Implement `_has_normalized_duplicates(values: list[str]) -> bool` with the existing `_normalize_text`. Implement `_e4_probe_failure` to return only the approved `e4_grader_probe_failed` evidence and a text-free remediation. Do not catch or persist Grader payloads.

- [x] **Step 4: Run focused tests and format changed files.**

  ```powershell
  python -m pytest apps/api/tests/test_question_verification.py -k e4 -q
  ruff check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ruff format apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ruff format --check apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  ```

  Expected: all focused E4 tests pass and both files are formatted.

- [x] **Step 5: Commit the implementation and focused tests.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify E4 candidate scoring points"
  ```

### Task 2: Verify scope and publish the reviewable change

**Files:**

- Modify: `docs/superpowers/plans/2026-07-21-ai-question-e4-verification.md`
- Verify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Verify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Confirms E4 uses only `VerificationGraderClient`, does not persist raw content, and preserves review-only semantics.
- Produces a reviewed pull request against `main`.

- [x] **Step 1: Run complete regression and static checks.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  git diff --check
  ```

  Expected: all tests pass; Ruff and whitespace checks succeed. The known Alembic `path_separator` deprecation warning is non-blocking.

- [x] **Step 2: Confirm the delivery boundary.**

  Inspect the diff and confirm all facts below:

  - E4 runs only after a successful common policy check.
  - A probe rule has one point and does not mutate the stored candidate rule.
  - Finding evidence has only counts, reason/probe categories, and numeric score values.
  - E4 probe success remains `needs_review`; no code auto-accepts or publishes E4.
  - `apps/api` gained no direct HTTP, LanguageTool, or similarity-model call and no `QuestionVersion` mutation.

- [x] **Step 3: Record delivery and open a pull request.**

  Mark completed plan steps, then run:

  ```powershell
  git add docs/superpowers/plans/2026-07-21-ai-question-e4-verification.md
  git commit -m "docs: record E4 verification delivery"
  git push -u origin codex/ai-question-e4-verification
  gh pr create --base main --head codex/ai-question-e4-verification --title "feat: verify E4 candidate scoring points"
  ```

  Expected: the PR contains only E4 verification code/tests and E4 design/plan documents.

## Plan Self-Review

- **Spec coverage:** Task 1 covers schema gating, normalized rubric uniqueness, tolerance-safe score totals, isolated review-only probes, dependency/default blocking, sanitized evidence, and immutable candidate state. Task 2 covers complete verification, boundary checks, and reviewable delivery.
- **Placeholder scan:** Every code change, test category, command, expectation, interface, and commit scope is explicit. No deferred implementation or vague error handling remains.
- **Type consistency:** `_e4_findings`, `_e4_probe_rule`, `_has_normalized_duplicates`, and `_e4_probe_failure` are defined in Task 1 and used with the existing `VerificationGraderClient` and `GradeResult` contracts.
