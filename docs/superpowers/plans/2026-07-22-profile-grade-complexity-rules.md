# Profile-grade complexity rules implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add profile-configured, deterministic grade-complexity warnings for generated candidates without adding an NLP dependency or a new MathJSON parser.

**Architecture:** Store validated optional limits on `CurriculumGradeMapping`; make import, export and curriculum-admin payloads round-trip them. A focused Core helper measures prompt lexical/sentence units, M1 numeric magnitude, and the existing Grader-normalized M2 AST, then appends stable sanitized warnings to the immutable verification run.

**Tech Stack:** Python 3.14, FastAPI, Pydantic v2, SQLAlchemy/Alembic, existing Grader MathJSON normalizer, pytest, Ruff.

## Global Constraints

- The only configuration owner is the target profile's `CurriculumGradeMapping`; never use a global grade mapping or a hidden fallback threshold.
- `complexity_rules_json` is an object with optional positive-integer `max_prompt_units`, `max_sentence_units`, `max_numeric_absolute_value`, and `max_math_operation_nodes` only.
- An empty rules object means no adopted complexity metric; malformed configured rules fail closed with `grade_complexity_rules_invalid` and evidence only `{"grade_level": "G5"}`.
- Exceeded valid limits are warnings using `grade_complexity_warning`; evidence is exactly grade level, metric name, observed numeric value, and limit—never prompt text, MathJSON, AST, raw numeric literal, exception, provider output, or learner data.
- Unicode lexical units count a Latin word/number token or one CJK ideograph; sentence separators are `.`, `!`, `?`, `。`, `！`, `？`.
- M2 complexity consumes only the existing `normalize_math_answer` safe AST. Core must not parse, evaluate, or normalize raw MathJSON itself, and normalization must happen exactly once per M2 candidate.
- Keep existing M2 invalid-normalizer behavior as blocked `m2_mathjson_invalid`, keep M1 non-finite values as policy failures, and never create/mutate a `QuestionVersion`.
- Warning findings remain append-only and draft-scoped; teacher acknowledgement and publication workflow stay owned by #41.

---

### Task 1: Persist and administer per-grade rule documents

**Files:**

- Create: `apps/api/alembic/versions/0018_curriculum_grade_complexity_rules.py`
- Modify: `apps/api/src/edu_grader_api/models.py`
- Modify: `apps/api/src/edu_grader_api/services/curriculum_imports.py`
- Modify: `apps/api/src/edu_grader_api/routers/curriculum.py`
- Modify: `apps/api/tests/test_curriculum_models.py`
- Modify: `apps/api/tests/test_curriculum_imports.py`
- Modify: `apps/api/tests/test_curriculum_api.py`

**Interfaces:**

- `CurriculumGradeMapping.complexity_rules_json: Mapped[dict[str, object]]` defaults to `{}`.
- `validate_complexity_rules(value: object) -> dict[str, int]` is the sole shape validator, defined in `services/curriculum_imports.py` and used by importer/router inputs before persistence.
- `ImportGradeMapping` and `CreateGradeMappingRequest` accept `complexity_rules: dict[str, object] = Field(default_factory=dict)`; exports return it as `complexity_rules`.

- [x] **Step 1: Write failing persistence and boundary tests.**

  Add tests that create a grade mapping without rules and observe `{}`, import/export a G5 mapping with all four limits, and reject each invalid configuration without writing a profile:

  ```python
  valid_rules = {
      "max_prompt_units": 80,
      "max_sentence_units": 20,
      "max_numeric_absolute_value": 1_000,
      "max_math_operation_nodes": 8,
  }

  @pytest.mark.parametrize("rules", [
      {"unknown": 1}, {"max_prompt_units": 0},
      {"max_prompt_units": True}, {"max_prompt_units": 1.5},
      {"max_prompt_units": -1}, [], None,
  ])
  def test_import_rejects_invalid_grade_complexity_rules(session: Session, rules: object) -> None:
      document_data = deepcopy(MINIMAL_DOCUMENT)
      document_data["grade_mappings"][0]["complexity_rules"] = rules
      with pytest.raises(ValidationError):
          ImportDocument.model_validate(document_data)
  ```

  Cover admin grade-mapping creation and active-profile export round-trip; assert a rejected request produces no new mapping or import batch.

- [x] **Step 2: Run the focused tests and confirm RED.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_curriculum_models.py tests/test_curriculum_imports.py tests/test_curriculum_api.py -k complexity -q
  ```

  Expected: failures because there is no rules column, payload field, or validator.

- [x] **Step 3: Add the migration, model field, and one strict validator.**

  Add Alembic revision `0018` with `down_revision = "0017"`, a non-null JSON/JSONB `complexity_rules_json` column and server/default `{}` for existing rows. Add the model field with `default=dict`.

  Implement the validator with the exact allowed-key set and positive plain `int` check (`bool` must be rejected):

  ```python
  _COMPLEXITY_RULE_KEYS = frozenset(
      {
          "max_prompt_units",
          "max_sentence_units",
          "max_numeric_absolute_value",
          "max_math_operation_nodes",
      }
  )

  def validate_complexity_rules(value: object) -> dict[str, int]:
      if not isinstance(value, dict) or set(value) - _COMPLEXITY_RULE_KEYS:
          raise ValueError("invalid complexity rules")
      rules: dict[str, int] = {}
      for key, limit in value.items():
          if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
              raise ValueError("invalid complexity limit")
          rules[key] = limit
      return rules
  ```

  Wire the validated value through JSON imports, CSV companion grade mappings, create-grade-mapping input, and active-profile export. Do not create an unrelated configuration endpoint.

- [x] **Step 4: Run focused tests and migration/static checks.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_curriculum_models.py tests/test_curriculum_imports.py tests/test_curriculum_api.py -k complexity -q
  ruff check src/edu_grader_api/models.py src/edu_grader_api/services/curriculum_imports.py src/edu_grader_api/routers/curriculum.py tests/test_curriculum_models.py tests/test_curriculum_imports.py tests/test_curriculum_api.py
  ruff format --check src/edu_grader_api/models.py src/edu_grader_api/services/curriculum_imports.py src/edu_grader_api/routers/curriculum.py tests/test_curriculum_models.py tests/test_curriculum_imports.py tests/test_curriculum_api.py
  ```

  Expected: all focused tests pass and Ruff reports no change.

- [x] **Step 5: Commit Task 1.**

  ```powershell
  git add apps/api/alembic/versions/0018_curriculum_grade_complexity_rules.py apps/api/src/edu_grader_api/models.py apps/api/src/edu_grader_api/services/curriculum_imports.py apps/api/src/edu_grader_api/routers/curriculum.py apps/api/tests/test_curriculum_models.py apps/api/tests/test_curriculum_imports.py apps/api/tests/test_curriculum_api.py
  git commit -m "feat: configure curriculum grade complexity rules"
  ```

### Task 2: Emit deterministic candidate-complexity warnings

**Files:**

- Modify: `apps/api/src/edu_grader_api/services/question_verification.py`
- Modify: `apps/api/tests/test_question_verification.py`

**Interfaces:**

- `_grade_complexity_findings(*, rules: dict[str, object], grade_level: str, prompt: str, question_type: object, rule_json: dict[str, object], normalized_m2_ast: dict[str, object] | None) -> list[VerificationFinding]`.
- `_m2_findings(rule_json: dict[str, object], policy_version: object, grader_client: VerificationGraderClient) -> tuple[list[VerificationFinding], dict[str, object] | None]` normalizes exactly once and returns the safe AST only on successful normalization.
- `_lexical_unit_count(text: str) -> int`, `_max_sentence_units(text: str) -> int`, and `_m2_complexity_metrics(ast: dict[str, object]) -> tuple[int | None, int]` are private, deterministic helpers.

- [x] **Step 1: Add RED tests for exact boundaries and sanitized output.**

  Give the G5 fixture these rules:

  ```python
  {"max_prompt_units": 4, "max_sentence_units": 2,
   "max_numeric_absolute_value": 10, "max_math_operation_nodes": 1}
  ```

  Add tests for exactly-four versus five lexical units, `"One two. Three four five."` sentence maximum of three, Latin/CJK mixed token counting, M1 `expected=11` and `tolerance=10` numeric-limit warnings, and M2 `Add(x, Multiply(2, x))` with two operator nodes. Assert a warning's evidence is exactly:

  ```python
  {"grade_level": "G5", "metric": "max_math_operation_nodes", "observed": 2, "limit": 1}
  ```

  Assert valid absent/empty rule documents produce no complexity finding; multiple exceeded metrics retain deterministic metric order. Assert evidence/remediation contains no prompt, MathJSON array, AST, or raw number text. Add a malformed persisted rules fixture and assert only `grade_complexity_rules_invalid` blocked evidence `{"grade_level": "G5"}`.

- [x] **Step 2: Run focused tests and confirm RED.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k "complexity or m2" -q
  ```

  Expected: failure because only the legacy global prompt-character lookup exists and M2 discards the normalizer output.

- [x] **Step 3: Replace the global lookup with deterministic profile rules.**

  Remove `_GRADE_TEXT_LIMITS`. Tokenize with one precompiled expression that treats a contiguous Latin/alphanumeric/apostrophe sequence as one unit and each CJK ideograph as one unit; split sentences only on the six specified separators. Never include source text in findings.

  In `_m2_findings`, call the existing `grader_client.normalize_math_answer` once, return its safe AST after the normalizer succeeds, and preserve the current blocked return on exceptions. Traverse that returned dict only by `type` and known child keys (`args`, `arg`, `numerator`, `denominator`, `base`, `exponent`): count `add`, `mul`, `neg`, `div`, and `pow` as operations; parse numeric `value` only with `Decimal(str(value))` to measure a finite absolute magnitude. Treat unexpected safe-AST shape as `m2_mathjson_invalid`, never as a pass.

  Invoke `_grade_complexity_findings` after common policy validation and the one M2 normalizer call. Append metrics in this fixed order: `max_prompt_units`, `max_sentence_units`, `max_numeric_absolute_value`, `max_math_operation_nodes`. Preserve existing M1/M2 Grader probes, duplicate/safety gates, immutable-run persistence, and `QuestionVersion` boundary.

- [x] **Step 4: Run focused tests, full verifier tests, and formatting.**

  ```powershell
  $env:PYTHONPATH = (Join-Path $PWD 'src')
  python -m pytest tests/test_question_verification.py -k "complexity or m2" -q
  python -m pytest tests/test_question_verification.py -q
  ruff check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  ruff format --check src/edu_grader_api/services/question_verification.py tests/test_question_verification.py
  git diff --check
  ```

  Expected: every complexity boundary and existing M1/M2 verifier test passes.

- [x] **Step 5: Commit Task 2.**

  ```powershell
  git add apps/api/src/edu_grader_api/services/question_verification.py apps/api/tests/test_question_verification.py
  git commit -m "feat: verify profile grade complexity"
  ```

### Task 3: Document the adoption boundary and perform full regression

**Files:**

- Modify: `docs/ai-question-generation-plan.md`
- Modify: `docs/superpowers/specs/2026-07-22-profile-grade-complexity-design.md`
- Modify: `docs/superpowers/plans/2026-07-22-profile-grade-complexity-rules.md`

**Interfaces:**

- Documents that rules are profile/grade specific, are warnings rather than auto-publication decisions, use a safe M2 AST, and do not replace #42 calibration or #41 acknowledgement.

- [x] **Step 1: Update documentation and task checkboxes.**

  Add a compact statement to the AI generation plan identifying the four configured metrics, stable warning evidence, profile owner, and deferred #42 calibration. Mark only completed task checkboxes in the spec/plan.

- [x] **Step 2: Run complete relevant verification.**

  ```powershell
  $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
  python -m pytest packages/processor-policy/tests services/generator/tests apps/api/tests services/grader/tests -q
  ruff check apps/api/src/edu_grader_api apps/api/tests
  ruff format --check apps/api/src/edu_grader_api apps/api/tests
  git diff --check
  ```

  Expected: all tests pass; only the established Alembic `path_separator` deprecation warning is allowed.

- [x] **Step 3: Audit delivery boundaries.**

  Confirm the final diff has no new NLP/model dependency, no raw candidate material in evidence, no Core MathJSON parser/evaluator, no second M2 normalizer call, no global grade fallback, no `QuestionVersion` mutation, and no #41 teacher-acknowledgement behavior.

- [x] **Step 4: Commit Task 3 and hand off for review.**

  ```powershell
  git add docs/ai-question-generation-plan.md docs/superpowers/specs/2026-07-22-profile-grade-complexity-design.md docs/superpowers/plans/2026-07-22-profile-grade-complexity-rules.md
  git commit -m "docs: record profile grade complexity verification"
  ```

## Plan self-review

- **Spec coverage:** Task 1 owns per-profile persistence and lifecycle/round-trip validation; Task 2 owns all four deterministic metrics, exact warning/block semantics, single normalized M2 AST use, and leak prevention; Task 3 records adoption boundaries and proves the integrated repository surface.
- **Placeholder scan:** Every task names files, interfaces, values, tests, commands, and commit scopes. No deferred implementation is hidden behind a placeholder.
- **Type consistency:** Task 1 produces `complexity_rules_json`; Task 2 consumes its mapping and returns standard `VerificationFinding` objects; Task 3 documents the same names, code values, and warning boundary.
