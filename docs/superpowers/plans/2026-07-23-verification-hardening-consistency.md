# Verification Hardening Consistency Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strict M1/M2 structured-consistency gate and a deterministic, independently runnable M1/M2 regression corpus for issue #83.

**Architecture:** The existing generated-candidate JSON becomes the single source of structured assertions. The provider contract requires M1/M2 assertions, the review service preserves them in immutable draft revisions, and `question_verification` compares them with existing policy values and Grader-normalized MathJSON. A test-only corpus adapter invokes the real verification service with deterministic doubles, while a small Make target prints type-stratified outcomes; it introduces no second validator.

**Tech Stack:** Python 3.13+, Pydantic v2, existing strict OpenAI Responses schema adapter, SQLAlchemy test fixtures, existing verification Grader protocol, pytest, Ruff, GNU Make, GitHub Actions.

## Global Constraints

- Do not add database columns, migrations, question types, automatic acceptance, automatic publication, #42 quality thresholds, or #43 governance controls.
- `generator-v3` M1/M2 candidates require assertions. Missing, malformed, or unsupported v3 assertions are blocked with stable sanitized findings; earlier Prompt versions keep their historical validation contract.
- `final_answer_text` is bounded text; `final_answer_mathjson` is a bounded JSON string so the provider's strict schema never needs an arbitrary object field.
- An M1 explanation must end with the exact normalized suffix `Final answer: <final_answer_text>`; M2 must do the same and its MathJSON assertion must normalize to the same safe AST as the rule expectation.
- Findings reveal only field names, question type, score presence, and rule/assertion versions; never values, MathJSON, prompt content, provider responses, or exceptions.
- Corpus execution uses the real `run_candidate_verification` service and deterministic grader doubles; it must not duplicate evaluator logic.

---

### Task 1: Version the candidate contract and provider prompt

**Files:**

- Modify: `services/generator/src/edu_generator/contracts.py:65-91`
- Modify: `services/generator/src/edu_generator/providers.py:28-49,62-84`
- Modify: `services/generator/src/edu_generator/prompt_templates.py:8,36-74`
- Modify: `apps/api/src/edu_grader_api/services/generation.py:45-47`
- Test: `services/generator/tests/test_contracts.py`
- Test: `apps/api/tests/test_generation_service.py`

**Interfaces:**

- Produces `VerificationAssertions(final_answer_text, final_answer_mathjson, declared_max_score)` and `GeneratedCandidate.verification_assertions`.
- `GeneratedCandidate.model_validate()` carries assertions through provider ingestion, draft persistence, teacher edits, and acceptance; the verifier applies the missing-assertion gate only to `generator-v3` drafts, so no separate API DTO is introduced.
- Produces `generator-v3` / `generated_question_candidates-v2`; new generation jobs use that cataloged prompt version.

- [ ] **Step 1: Write failing contract tests.**

Add an M1 payload without assertions and an M2 payload with null MathJSON to the parametrized invalid-candidate tests. Add a valid M1 candidate with:

```python
"verification_assertions": {
    "final_answer_text": "4",
    "final_answer_mathjson": None,
    "declared_max_score": 1,
}
```

and a valid M2 candidate with `final_answer_mathjson` equal to a JSON string for `["Add", "x", 1]`. Assert the strict Responses schema requires `verification_assertions`, permits nullable M2-only MathJSON, and does not expose an arbitrary object field. Assert `resolve_prompt_template("generator-v3", ["M1"])` instructs the required final-answer suffix.

- [ ] **Step 2: Run the tests to verify they fail for contract absence.**

Run:

```powershell
$env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
python -m pytest services/generator/tests/test_contracts.py -k "assertion or schema or prompt" -q
```

Expected: FAIL because `GeneratedCandidate` does not define or require `verification_assertions` and `generator-v3` is unknown.

- [ ] **Step 3: Add the smallest strict contract.**

In `contracts.py`, add:

```python
class VerificationAssertions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    final_answer_text: str = Field(min_length=1, max_length=2_000)
    final_answer_mathjson: str | None = Field(default=None, max_length=20_000)
    declared_max_score: float = Field(gt=0, le=100)
```

Add `verification_assertions: VerificationAssertions | None = None` to `GeneratedCandidate`. When assertions are present, its model validator requires null MathJSON for M1, non-null MathJSON for M2, and null assertions for E1-E4. The v3 strict Responses schema and prompt make the field required for active M1/M2 generation; the verifier, not the parser, blocks a missing v3 assertion so legacy drafts remain readable. Update `FakeGenerationProvider` to create the M1/M2 values, including `json.dumps(rule["expected"], separators=(",", ":"))` for M2. Add a v3 prompt template with a v2 schema identifier and final-answer instructions; make `GENERATION_PROMPT_VERSION` select v3.

- [ ] **Step 4: Run the focused contract tests.**

Run the Step 2 command plus:

```powershell
python -m pytest apps/api/tests/test_generation_service.py -q
```

Expected: PASS; fake-provider drafts persist the assertion object intact.

- [ ] **Step 5: Commit the contract slice.**

```powershell
git add services/generator/src/edu_generator/contracts.py services/generator/src/edu_generator/providers.py services/generator/src/edu_generator/prompt_templates.py apps/api/src/edu_grader_api/services/generation.py services/generator/tests/test_contracts.py apps/api/tests/test_generation_service.py
git commit -m "feat: require structured candidate assertions"
```

### Task 2: Fail closed on M1/M2 assertion inconsistencies

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py:200-380,383-495,829-932`
- Modify: `apps/api/src/edu_grader_api/routers/ai_question_validation.py:37-80`
- Test: `apps/api/tests/test_question_verification.py`
- Test: `apps/api/tests/test_ai_question_generation_api.py`

**Interfaces:**

- Produces stable blocked findings: `answer_explanation_inconsistent`, `score_total_inconsistent`, and `unsupported_consistency_structure`.
- Consumes `candidate["verification_assertions"]`, generation-job prompt version, existing M1 `expected`/`tolerance`, existing M2 normalizer, and effective maximum score (`rule_json["max_score"]` or `1`).
- The public finding allowlist gains only the assertion evidence keys; serialized API findings remain sanitized.

- [ ] **Step 1: Write failing M1/M2 service tests.**

Extend `valid_m1_candidate()` and `valid_m2_candidate()` to include valid assertions. Add tests that independently assert:

```python
assert "answer_explanation_inconsistent" in finding_codes(run)  # wrong M1 final_answer_text
assert "score_total_inconsistent" in finding_codes(run)         # M2 declared_max_score != max_score
assert "unsupported_consistency_structure" in finding_codes(run) # bad JSON M2 assertion
```

For the explanation test, replace the ending with `Final answer: 5` while retaining an assertion of `4`; assert evidence is exactly `{"question_type": "M1", "field": "explanation_suffix"}`. For M2, use a different normalizable MathJSON value and assert the blocked evidence names `final_answer_mathjson` without storing the value. Also assert a blocked current revision cannot be accepted through the existing review service.

- [ ] **Step 2: Run the tests to verify the expected failures.**

Run:

```powershell
$env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
python -m pytest apps/api/tests/test_question_verification.py -k "assertion or explanation_inconsistent or score_total_inconsistent" -q
```

Expected: FAIL because the verifier currently ignores `verification_assertions`.

- [ ] **Step 3: Implement minimal assertion helpers.**

Add narrow M1/M2 consistency helpers and call them after policy validation and before their type-specific Grader probes. They must gate missing assertions only when the job uses `generator-v3`:

```python
if job.prompt_version == "generator-v3" and not isinstance(assertions, dict):
    return [_blocked("unsupported_consistency_structure", {"question_type": question_type, "field": "verification_assertions"}, remediation)]
```

For M1, construct `Decimal(final_answer_text)` and compare exactly to `Decimal(str(expected))`; require `final_answer_mathjson is None`; require the normalized explanation suffix; compare the declared score with `1`. For M2, parse the JSON string, normalize it with `grader_client.normalize_math_answer({"mathjson": asserted, "variables": variables})`, compare the safe AST with the already normalized rule AST, require the suffix, and compare declared score with `float(rule_json.get("max_score", 1))`. Convert parsing, normalization, non-finite score, or unsupported field shape to `unsupported_consistency_structure`; never propagate an exception or call an unrelated probe.

Use `_blocked()` with exact evidence fields and update the router's safe evidence allowlist so all new evidence is serializable but no assertion value is exposed.

- [ ] **Step 4: Run focused verification and review-boundary tests.**

Run:

```powershell
python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_ai_question_generation_api.py -q
```

Expected: PASS; a blocked consistency run remains non-acceptable and existing E3/E4 review behavior is unaffected.

- [ ] **Step 5: Commit the verifier slice.**

```powershell
git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/src/edu_grader_api/routers/ai_question_validation.py apps/api/tests/test_question_verification.py apps/api/tests/test_ai_question_generation_api.py
git commit -m "feat: block inconsistent ai candidate assertions"
```

### Task 3: Add the deterministic M1/M2 corpus adapter and command

**Files:**

- Create: `apps/api/tests/fixtures/verification_corpus/m1.json`
- Create: `apps/api/tests/fixtures/verification_corpus/m2.json`
- Create: `apps/api/tests/test_verification_corpus.py`
- Modify: `Makefile:1-37`
- Modify: `.github/workflows/ci.yml:35-38`

**Interfaces:**

- Corpus format: `{ "version": 1, "question_type": "M1", "cases": [...] }`.
- Each case has `id`, `candidate_mutation`, `grader_profile`, `expected_status`, and `expected_codes`.
- `python -m pytest apps/api/tests/test_verification_corpus.py -q -rA` is the runner; `make verification-regression` is its discoverable alias.

- [ ] **Step 1: Write failing corpus-loader tests and initial JSON cases.**

Create one M1 correct case, one wrong-final-answer case, one empty-answer assertion case, one inclusive-boundary case, and one common-misconception case. Create equivalent M2 cases for correct expected MathJSON, one-unit offset, empty MathJSON, required-form mismatch, and resource-limit probe. In `test_verification_corpus.py`, load both files, create drafts using shared deterministic fixtures, select grader profiles, and assert the persisted status and ordered codes exactly.

Add a summary assertion that groups cases by the JSON `question_type` and returns a line shaped as:

```text
verification corpus: M1 total=5 passed=5 failed=0
```

- [ ] **Step 2: Run the adapter to verify it fails before implementation.**

Run:

```powershell
$env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
python -m pytest apps/api/tests/test_verification_corpus.py -q -rA
```

Expected: FAIL because the corpus adapter and fixtures do not exist.

- [ ] **Step 3: Implement only the corpus adapter and Make target.**

Keep all fixture materialization and grader doubles in `test_verification_corpus.py`; production modules must not import corpus files. Use `json.loads()` and validate exact top-level keys before running a case. Reject duplicate case IDs, an unexpected question type, non-list expected codes, or a missing deterministic grader profile with an assertion that includes the case ID but not candidate content.

Add:

```make
verification-regression:
	python -m pytest apps/api/tests/test_verification_corpus.py -q -rA
```

to `Makefile`, then add a `Run deterministic verification corpus` step after `Test Python packages` in the existing `python` CI job. The CI command is the Make target itself.

- [ ] **Step 4: Run the new command and focused suite.**

Run:

```powershell
make verification-regression
python -m pytest apps/api/tests/test_question_verification.py apps/api/tests/test_verification_corpus.py -q
```

Expected: PASS with M1/M2 totals and no leaked candidate content in failure diagnostics.

- [ ] **Step 5: Commit the corpus skeleton.**

```powershell
git add apps/api/tests/fixtures/verification_corpus/m1.json apps/api/tests/fixtures/verification_corpus/m2.json apps/api/tests/test_verification_corpus.py Makefile .github/workflows/ci.yml
git commit -m "test: add deterministic m1 m2 verification corpus"
```

### Task 4: Verify the PR-1 boundary and document delivery evidence

**Files:**

- Modify: `docs/superpowers/plans/2026-07-23-verification-hardening-consistency.md`
- Verify: `services/generator/src/edu_generator/contracts.py`
- Verify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Verify: `apps/api/tests/test_verification_corpus.py`

- [ ] **Step 1: Run formatting and static checks.**

```powershell
python -m ruff check services/generator apps/api
python -m ruff format --check services/generator apps/api
```

- [ ] **Step 2: Run the complete affected test surface with explicit source paths.**

```powershell
$env:PYTHONPATH = "$(Join-Path $PWD 'apps\\api\\src');$(Join-Path $PWD 'services\\generator\\src');$(Join-Path $PWD 'packages\\processor-policy\\src');$(Join-Path $PWD 'services\\grader\\src')"
python -m pytest services/generator/tests apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_generation_api.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_question_verification.py apps/api/tests/test_verification_corpus.py -q
make verification-regression
```

- [ ] **Step 3: Inspect scope and sensitive-output boundaries.**

```powershell
git diff --check main...HEAD
git diff --name-only main...HEAD
rg -n "verification_assertions|answer_explanation_inconsistent|score_total_inconsistent|unsupported_consistency_structure" services/generator apps/api
```

Confirm no migration appears, no E3/E4 acceptance path changes, and new evidence never includes a prompt, final-answer text, MathJSON, or raw exception.

- [ ] **Step 4: Record actual commands and results, then commit evidence only if this file changed.**

Append a dated `## Delivery verification` section containing command, exit code, and passed-test count from Steps 1-3. Then:

```powershell
git add docs/superpowers/plans/2026-07-23-verification-hardening-consistency.md
git commit -m "docs: record verification hardening evidence"
```

## Delivery verification — 2026-07-23

- Explicit-source pytest bundle covering generator contracts, generation, review, verification, and corpus tests: exit 0; 338 passed.
- `make verification-regression` with the same source paths: exit 0; M1 total=5 passed=5 failed=0 and M2 total=5 passed=5 failed=0.
- `python -m ruff check services/generator apps/api` and `python -m ruff format --check services/generator apps/api`: exit 0.
- `git diff --check`: exit 0; the slice adds no migration and does not change E3/E4 acceptance paths.

## Final verification hardening evidence — 2026-07-23

- Deterministic corpus: M1=21, M2=21, E1=20, E2=20, E3=20, E4=20. It includes rule/assertion conflicts, grader and LanguageTool failures, similarity client timeout/invalid responses, malicious deep safe ASTs, overlong text, and Unicode normalization conflicts.
- E3 and E4 corpus cases assert `pending_review` after every validation run; blocked candidates remain rejected by existing review-boundary tests.
- Full explicit-source affected suite: exit 0; 342 passed across generator contracts, generation, review, question verification, and corpus tests.
- `make verification-regression`: exit 0; every corpus case reports its expected status and stable Finding Codes.
- `python -m ruff check services/generator apps/api`, `python -m ruff format --check services/generator apps/api`, and `git diff --check`: exit 0.
