# Candidate Content-Safety Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four-term safety check with a deterministic, versioned candidate-content policy that blocks clearly unsafe minor content and direct reproduction requests, while warning on context-dependent mature themes.

**Architecture:** Add a focused local policy module that normalizes candidate text and returns sanitized typed matches. Make `_safety_findings` translate those matches into existing immutable verification findings, persist the policy version in each run's feature summary, and increment the verifier/ruleset versions. No new database object, HTTP client, model, or publication path is introduced.

**Tech Stack:** Python 3.14, standard-library `dataclasses`, `re`, `unicodedata`, existing SQLAlchemy verification persistence, pytest, Ruff.

## Global Constraints

- Scan only generated-candidate fields already passed to `_safety_findings`: prompt, explanation, reading material and textual rule values.
- Use no hosted moderation provider, model runtime, new Python dependency, migration, Grader call or processor-policy change.
- Normalize with NFKC/casefold, whitespace collapse and separator collapse; do not persist any source text, snippet, offset or exception text.
- Emit exact evidence keys `category`, `rule_id`, and `policy_version` for every content-policy finding.
- Keep `unsafe_minor_content` and `copyright_reproduction_risk` blocked; keep `mature_theme_requires_review` warning.
- Advance `VALIDATOR_VERSION` to `verification-v4`, `RULESET_VERSION` to `rules-v4`, and persist `CONTENT_POLICY_VERSION` in `feature_summary_json`.
- Treat direct reproduction only as this issue's candidate-time gate. Licence records, request filtering, takedowns, provider governance and semantic evaluation remain #43/#42 work.

---

### Task 1: Build the deterministic candidate-content policy

**Files:**

- Create: `apps/api/src/edu_grader_api/services/candidate_content_policy.py`
- Create: `apps/api/tests/test_candidate_content_policy.py`

**Interfaces:**

- Produces `CONTENT_POLICY_VERSION = "minor-content-policy-v1"`.
- Produces `ContentPolicyMatch(code: str, severity: Literal["warning", "blocked"], category: str, rule_id: str, remediation: str)`.
- Produces `find_candidate_content_matches(texts: Iterable[str]) -> tuple[ContentPolicyMatch, ...]`.
- Consumes only strings and standard-library normalization/regular-expression utilities.

- [ ] **Step 1: Write failing policy-unit tests.**

  Create tests that assert the public scanner returns sanitized matches only. Use deliberately bounded fixtures, including: an NFKC/case/separator variant of an explicit adult-content phrase; an explicit self-harm method request; graphic-violence wording; an explicit dangerous-device instruction; a directed demeaning protected-class assertion; a direct textbook-page/full-passage/question-bank reproduction request; and a drug-use theme.

  Assert the adult fixture is represented exactly as:

  ```python
  assert matches == (
      ContentPolicyMatch(
          code="unsafe_minor_content",
          severity="blocked",
          category="adult_content",
          rule_id="adult-explicit-v1",
          remediation="Remove unsafe content before asking for teacher review.",
      ),
  )
  ```

  Add a multi-category fixture and assert match order follows declared policy order. Add neutral `"Discuss how to seek help when someone is self-harming."`, neutral protected-class material, anti-bias material, and `"Write an original practice question about fractions."` fixtures; assert each returns `()`.

- [ ] **Step 2: Run the focused policy tests and confirm they fail.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_candidate_content_policy.py -q
  ```

  Expected: collection failure because `candidate_content_policy` does not exist.

- [ ] **Step 3: Implement the minimal reviewed policy module.**

  Add the immutable match contract, an ordered tuple of internally compiled rules, and the public scanner:

  ```python
  CONTENT_POLICY_VERSION = "minor-content-policy-v1"

  @dataclass(frozen=True)
  class ContentPolicyMatch:
      code: str
      severity: Literal["warning", "blocked"]
      category: str
      rule_id: str
      remediation: str

  def find_candidate_content_matches(texts: Iterable[str]) -> tuple[ContentPolicyMatch, ...]:
      normalized = _normalized_forms(texts)
      matches: list[ContentPolicyMatch] = []
      seen: set[tuple[str, str, str]] = set()
      for rule in _RULES:
          if any(pattern.search(value) for pattern, value in zip(rule.patterns, normalized, strict=True)):
              key = (rule.code, rule.category, rule.rule_id)
              if key not in seen:
                  seen.add(key)
                  matches.append(rule.as_match())
      return tuple(matches)
  ```

  Implement `_normalized_forms` as NFKC + `casefold`, whitespace collapse, and a second form with separator characters removed. Keep every pattern bounded: Latin terms use non-alphanumeric boundaries; Chinese patterns are exact phrases. Define the exact categories and codes in the approved design. Do not add fuzzy matching, a model score, candidate text, or location data to `ContentPolicyMatch`.

- [ ] **Step 4: Run focused policy tests and static checks.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_candidate_content_policy.py -q
  ruff check src/edu_grader_api/services/candidate_content_policy.py tests/test_candidate_content_policy.py
  ruff format src/edu_grader_api/services/candidate_content_policy.py tests/test_candidate_content_policy.py
  ruff format --check src/edu_grader_api/services/candidate_content_policy.py tests/test_candidate_content_policy.py
  ```

  Expected: all new policy tests pass; Ruff reports no violations.

### Task 2: Integrate policy findings into immutable verification runs

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- Consumes `CONTENT_POLICY_VERSION`, `ContentPolicyMatch`, and `find_candidate_content_matches` from `candidate_content_policy.py`.
- Preserves `_safety_findings(*texts: str) -> list[VerificationFinding]` as the private integration seam.
- Produces only existing `VerificationFinding` and `GenerationValidationRun` objects.

- [ ] **Step 1: Write failing integration tests through `run_candidate_verification`.**

  Add candidate fixtures that put a blocked pattern in `reading_material` and a second blocked pattern in a nested rule value. Assert a blocked run contains two findings ordered by policy order and each evidence payload is exactly:

  ```python
  {
      "category": "adult_content",
      "rule_id": "adult-explicit-v1",
      "policy_version": "minor-content-policy-v1",
  }
  ```

  Assert neither `evidence_json`, remediation nor `feature_summary_json` contains the fixture's sensitive text. Add a context-dependent mature-theme candidate and assert `ValidationRunStatus.WARNING` with one `mature_theme_requires_review` finding. Add direct reproduction fixture and assert `copyright_reproduction_risk` is blocked. Preserve the existing public unsafe-content test by updating only its expected sanitized metadata.

- [ ] **Step 2: Run focused integration tests and confirm they fail.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k "unsafe or safety or content_policy or reproduction" -q
  ```

  Expected: failures because the existing helper emits only one two-key `unsafe_minor_content` finding and has no copyright or warning handling.

- [ ] **Step 3: Implement the thin verification adapter and audit versions.**

  Replace the `_UNSAFE_MINOR_TERMS` loop with:

  ```python
  def _safety_findings(*texts: str) -> list[VerificationFinding]:
      return [
          VerificationFinding(
              code=match.code,
              severity=ValidationFindingSeverity(match.severity),
              evidence={
                  "category": match.category,
                  "rule_id": match.rule_id,
                  "policy_version": CONTENT_POLICY_VERSION,
              },
              remediation=match.remediation,
          )
          for match in find_candidate_content_matches(texts)
      ]
  ```

  Import the policy module at the top of `question_verification.py`. Set `VALIDATOR_VERSION = "verification-v4"`, `RULESET_VERSION = "rules-v4"`, and add `"content_policy_version": CONTENT_POLICY_VERSION` to `_persist_run`'s `feature_summary_json`. Leave the candidate-field fan-in, `_status_for`, persistence mechanics and public routing unchanged.

- [ ] **Step 4: Run focused integration tests, full verifier tests, and format.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_candidate_content_policy.py tests/test_question_verification.py -q
  ruff check src/edu_grader_api/services/candidate_content_policy.py src/edu_grader_api/services/question_verification.py tests/test_candidate_content_policy.py tests/test_question_verification.py
  ruff format --check src/edu_grader_api/services/candidate_content_policy.py src/edu_grader_api/services/question_verification.py tests/test_candidate_content_policy.py tests/test_question_verification.py
  ```

  Expected: all policy and verification tests pass and formatting is clean.

### Task 3: Document the operational boundary and validate the delivery

**Files:**

- Modify: `docs/ai-question-generation-plan.md`
- Modify: `docs/superpowers/specs/2026-07-22-candidate-content-safety-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-candidate-content-safety.md`
- Verify: `apps/api/src/edu_grader_api/services/candidate_content_policy.py`
- Verify: `apps/api/src/edu_grader_api/services/question_verification.py`

**Interfaces:**

- Documents deterministic candidate-time scanning, warning/block semantics, versioning, and ownership handoff to Issue #42/#43.
- Produces a ready-for-review branch that contains implementation, tests, design and plan only.

- [ ] **Step 1: Update the AI generation plan.**

  In the verification section, add a compact statement that generated candidate fields are checked locally against `minor-content-policy-v1`; explicit unsafe content and direct reproduction requests block, context-dependent mature themes warn, and evidence contains only category/rule/policy metadata. State that policy expansion needs #42 evaluation and that licensing, teacher-request filtering and takedown work belong to #43.

- [ ] **Step 2: Run complete relevant regression and static verification.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  git diff --check
  ```

  Expected: tests, Ruff and whitespace checks pass. Treat only the established Alembic `path_separator` deprecation warning as non-blocking.

- [ ] **Step 3: Perform boundary review before commit.**

  Verify the diff proves all of the following:

  - no candidate string, normalized string, snippet, offset or exception message can reach persisted evidence, remediation or feature summary;
  - every policy rule has a stable ID, category, code, severity and remediation, and the public scanner returns deterministic ordered matches;
  - neutral identity, support-oriented self-harm, anti-bias and original-exercise cases remain unflagged;
  - no network import, model dependency, migration, Grader call, `QuestionVersion` mutation or provider configuration was added;
  - `verification-v4`, `rules-v4` and `minor-content-policy-v1` are persisted for new runs;
  - the docs explicitly preserve #42/#43 ownership boundaries.

- [ ] **Step 4: Commit, push and open the required PR.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/candidate_content_policy.py apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_candidate_content_policy.py apps/api/tests/test_question_verification.py docs/ai-question-generation-plan.md docs/superpowers/specs/2026-07-22-candidate-content-safety-design.md docs/superpowers/plans/2026-07-22-candidate-content-safety.md
  git commit -m "feat: verify unsafe generated question content"
  git push -u origin codex/content-safety-policy
  gh pr create --base main --head codex/content-safety-policy --title "feat: verify unsafe generated question content" --body-file .github/pull_request_template.md
  ```

  Expected: a PR against `main` containing exactly this bounded verification slice. Replace the template body with a concise summary, validation output, and explicit #40/#42/#43 boundary statement if the repository does not have that template.

## Plan Self-Review

- **Spec coverage:** Task 1 supplies the local versioned policy and safe normalization; Task 2 gives every policy result stable immutable evidence and run-version auditability; Task 3 documents the boundary, runs regression checks, and creates the required reviewable PR.
- **Placeholder scan:** All tasks name exact files, public/private interfaces, required evidence shape, test commands and delivery commands. No unspecified behaviour, deferred safety rule or generic validation remains.
- **Type consistency:** `ContentPolicyMatch.severity` maps directly to `ValidationFindingSeverity`, policy evidence keys are identical in design, tests and adapter, and the existing `VerificationFinding` persistence interface is unchanged.
