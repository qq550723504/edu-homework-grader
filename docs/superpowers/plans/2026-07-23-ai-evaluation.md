# AI Question Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a deterministic make ai-evaluation release gate that writes JSON and HTML quality reports and blocks unsuitable AI question-generation versions.

**Architecture:** Add a pure Core API evaluation module that validates de-identified JSONL records against a versioned policy, calculates global and fully keyed stratified metrics, and emits stable violations plus a promotion recommendation. A CLI writes both artifacts before returning its release-gate exit status. Existing generator model-snapshot validation is reused for immutable model-ID checks; existing Grader calibration remains its separate E1--E4 scoring-calibration owner.

**Tech Stack:** Python 3.12+, Pydantic v2, pytest, standard-library JSON/HTML rendering, GNU Make, existing edu_generator.model_snapshots.

## Global Constraints

- Do not read operational databases or include real student answers, identities, or candidate bodies.
- Do not add a migration, dashboard/API route, canary routing, default-version mutation, or a #43 governance control.
- Treat policy thresholds and approved versions as versioned fixture/configuration data, never evaluator constants.
- Write both artifacts/ai-evaluation/report.json and artifacts/ai-evaluation/report.html before returning a non-zero gate result.
- Reuse validate_immutable_openai_model_id from edu_generator.model_snapshots; do not create another model-ID regex.
- Preserve E3/E4 teacher review: pending_review cannot count as accepted or reviewed publication.
- Use stable, content-free violation codes in all tests and reports.
- Run every production-code change through a red-green pytest cycle before committing.

---

## File Structure

| File | Responsibility |
| --- | --- |
| apps/api/src/edu_grader_api/services/ai_evaluation.py | Record/policy contracts, metric computation, strata/version comparison, report serialization, HTML renderer, CLI. |
| apps/api/tests/test_ai_evaluation.py | Unit and CLI behavior tests, including every blocking probe. |
| apps/api/tests/fixtures/ai_evaluation/policy-v1.json | Versioned approved model/Prompt lists and release thresholds. |
| apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl | Authorized synthetic, de-identified baseline records for M1, M2, E1--E4. |
| Makefile | ai-evaluation target and phony registration. |
| .gitignore | Exclude only generated artifacts/ai-evaluation files. |

The module exposes:

    class EvaluationPolicy(BaseModel): ...
    class EvaluationRecord(BaseModel): ...
    class EvaluationReport(BaseModel): ...
    def load_policy(path: Path) -> EvaluationPolicy: ...
    def load_records(path: Path) -> list[EvaluationRecord]: ...
    def evaluate_records(
        records: Sequence[EvaluationRecord], policy: EvaluationPolicy
    ) -> EvaluationReport: ...
    def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]: ...
    def main(argv: Sequence[str] | None = None) -> int: ...

CLI positional arguments are POLICY_PATH RECORDS_PATH OUTPUT_DIRECTORY. The Make target passes the committed policy and golden dataset to artifacts/ai-evaluation.

### Task 1: Define the de-identified data contract and policy-driven gate

**Files:**

- Create: apps/api/src/edu_grader_api/services/ai_evaluation.py
- Create: apps/api/tests/test_ai_evaluation.py
- Create: apps/api/tests/fixtures/ai_evaluation/policy-v1.json

**Interfaces:**

- Consumes a policy-v1.json object containing policy_id, approved_model_ids, approved_prompt_versions, and named threshold values.
- Consumes EvaluationRecord fields for all required report dimensions, deterministic run metadata, validation outcomes, teacher outcome, publication/review evidence, cost, and duration.
- Produces EvaluationReport.promotion_eligible, globally keyed metrics, and stable violation objects with code, metric, and non-sensitive location metadata.

- [ ] **Step 1: Write failing contract and threshold tests.**

  Create test_ai_evaluation.py with construction helpers and this minimal gate expectation:

    def test_evaluate_records_passes_versioned_baseline_policy() -> None:
        report = evaluation.evaluate_records(_passing_records(), _policy())
        assert report.promotion_eligible is True
        assert report.violations == []

    @pytest.mark.parametrize(
        ("mutate", "code"),
        [
            (_wrong_math_answer, "evaluation_math_answer_error_rate_above_threshold"),
            (_out_of_grade, "evaluation_grade_mismatch_rate_above_threshold"),
            (_duplicate_candidate, "evaluation_similarity_rate_above_threshold"),
        ],
    )
    def test_evaluate_records_blocks_quality_regressions(mutate, code) -> None:
        report = evaluation.evaluate_records(mutate(_passing_records()), _policy())
        assert report.promotion_eligible is False
        assert code in {violation.code for violation in report.violations}

  Run:

    $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src')"
    python -m pytest apps/api/tests/test_ai_evaluation.py -q

  Expected: FAIL during collection because edu_grader_api.services.ai_evaluation does not exist.

- [ ] **Step 2: Add minimal strict Pydantic policy and record models.**

  In ai_evaluation.py, declare QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"] and TeacherOutcome = Literal["accepted_directly", "accepted_after_edit", "rejected", "pending_review"]. Use ConfigDict(extra="forbid") for policy and records. Require non-empty identifiers, finite non-negative cost/duration, immutable model ID, non-empty Prompt and validator versions, and the eight required reporting-dimension fields.

  Implement load_policy and load_records using Pydantic validation. Wrap malformed JSONL with only the file line number and Pydantic field location; never echo a raw candidate body.

- [ ] **Step 3: Implement global metric computation and stable violations.**

  Implement one count/rate helper that returns numerator, denominator, rate or None, threshold, comparator, and state. Calculate:

    schema_pass_rate
    math_answer_error_rate
    grade_mismatch_rate
    duplicate_or_similarity_rate
    teacher_direct_accept_rate
    teacher_modified_accept_rate
    published_without_teacher_review_count
    rejection_reason_counts
    cost_per_final_accepted_question
    end_to_end_duration_ms

  Use policy values for all comparators. Count M1/M2 answer error only where math_answer_correct is present. Count direct acceptance over reviewed candidates; modified acceptance over edited candidates; pending review as neither. A record with both duplicate flags counts once. Aggregate structured rejection categories, total cost divided by final accepted records, and observed duration statistics without treating those three evidence metrics as release thresholds in policy-v1. Return the specified stable threshold codes when a global metric fails.

- [ ] **Step 4: Verify the green cycle and commit.**

  Run:

    $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src')"
    python -m pytest apps/api/tests/test_ai_evaluation.py -q
    python -m ruff check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    python -m ruff format --check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    git diff --check
    git add apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py apps/api/tests/fixtures/ai_evaluation/policy-v1.json
    git commit -m "feat: add ai evaluation quality gate"

  Expected: baseline passes and wrong-answer, out-of-grade, and duplicate probes each fail with their exact code.

### Task 2: Add version approval, strata, and comparison evidence

**Files:**

- Modify: apps/api/src/edu_grader_api/services/ai_evaluation.py
- Modify: apps/api/tests/test_ai_evaluation.py

**Interfaces:**

- Consumes policy approval lists and each record's immutable model_id, prompt_version, and validator_version.
- Produces version_summaries keyed by (model_id, prompt_version, validator_version) and strata keyed by (curriculum_profile, grade, subject, question_type, model_id, prompt_version, validator_version, difficulty_band).
- Produces violation codes evaluation_unapproved_model, evaluation_unapproved_prompt, and evaluation_published_without_teacher_review.

- [ ] **Step 1: Write failing version and strata tests.**

  Add tests that mutate a valid record to gpt-4o and generator-floating-v1. Assert the first returns evaluation_unapproved_model and the second returns evaluation_unapproved_prompt. Add a published record with absent review evidence and assert evaluation_published_without_teacher_review.

  Assert the report includes all eight strata fields, rejection-reason counts, accepted-question cost, duration evidence, and separate version summaries when two model/Prompt tuples are present:

    assert set(report.strata[0].key) == {
        "curriculum_profile", "grade", "subject", "question_type",
        "model_id", "prompt_version", "validator_version", "difficulty_band",
    }
    assert len(report.version_summaries) == 2

  Run focused test selectors. Expected: FAIL because version approval, strata, and version summaries are not implemented.

- [ ] **Step 2: Reuse immutable model validation and add approval checks.**

  Import validate_immutable_openai_model_id from edu_generator.model_snapshots. Convert its ValueError into a content-free record validation violation. Separately compare valid immutable IDs and Prompt versions to policy approval lists, so an immutable but unapproved candidate is still blocked.

  Evaluate policy violations before threshold aggregation and set promotion_eligible=False whenever any record-level violation exists.

- [ ] **Step 3: Add deterministic grouping and version comparison data.**

  Sort every group by its tuple key. Reuse the metric function from Task 1 for each stratum and version summary. Include per-version metric deltas against the lexically first approved version key so a two-version report explicitly shows candidate degradation without relying on a total average. A populated stratum that fails a metric emits a violation with its metadata; no raw candidate data appears in the key or diagnostics.

- [ ] **Step 4: Verify the green cycle and commit.**

  Run:

    $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src')"
    python -m pytest apps/api/tests/test_ai_evaluation.py -q
    python -m ruff check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    python -m ruff format --check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    git diff --check
    git add apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    git commit -m "feat: report ai evaluation strata"

  Expected: floating/unapproved versions, unpublished review evidence, and any populated failing stratum block promotion with stable codes.

### Task 3: Emit deterministic artifacts and the Make entry point

**Files:**

- Modify: apps/api/src/edu_grader_api/services/ai_evaluation.py
- Modify: apps/api/tests/test_ai_evaluation.py
- Modify: Makefile
- Modify: .gitignore

**Interfaces:**

- write_report(report, output_dir) creates report.json and report.html and returns their paths.
- main([POLICY_PATH, RECORDS_PATH, OUTPUT_DIRECTORY]) returns 0 only when promotion_eligible is true; it returns 1 after writing artifacts when the gate blocks.
- make ai-evaluation runs the committed policy/fixture into artifacts/ai-evaluation.

- [ ] **Step 1: Write failing CLI and artifact tests.**

  Add a tmp_path test that calls main with a passing fixture and asserts exit 0, both files exist, JSON has promotion_eligible: true, and escaped HTML has the policy ID plus every metric name. Add the wrong-answer fixture mutation and assert exit 1 while both artifacts still exist.

  Run the two tests. Expected: FAIL because report writers and main do not exist.

- [ ] **Step 2: Implement serialization, escaped HTML, and exit behavior.**

  Serialize a Pydantic report with model_dump(mode="json") and json.dumps using ensure_ascii=False, indent=2, and sort_keys=True. Build HTML only from escaped report values using html.escape; include policy/input identifiers, promotion status, global metrics, version summaries, strata, and violations. Create the output directory with parents=True and exist_ok=True, write both files, and return the gate status afterward.

- [ ] **Step 3: Add the Make target and ignored artifact directory.**

  Add ai-evaluation to .PHONY and:

    ai-evaluation:
        python -m edu_grader_api.services.ai_evaluation apps/api/tests/fixtures/ai_evaluation/policy-v1.json apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl artifacts/ai-evaluation

  Add only /artifacts/ai-evaluation/ to .gitignore, leaving future non-evaluation evidence trackable by explicit choice.

- [ ] **Step 4: Verify the green cycle and commit.**

  Run:

    $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src')"
    python -m pytest apps/api/tests/test_ai_evaluation.py -q
    make ai-evaluation
    Test-Path artifacts/ai-evaluation/report.json
    Test-Path artifacts/ai-evaluation/report.html
    python -m ruff check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    python -m ruff format --check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    git diff --check
    git add apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py Makefile .gitignore
    git commit -m "feat: add ai evaluation report command"

  Expected: command exits 0 for the golden baseline and its two artifacts exist. Test-only bad input exits 1 after producing both artifacts.

### Task 4: Commit the representative golden corpus and prove every release blocker

**Files:**

- Create: apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl
- Modify: apps/api/tests/test_ai_evaluation.py

**Interfaces:**

- Golden records cover M1, M2, E1, E2, E3, and E4, all policy-reporting fields, teacher outcomes, publication evidence, finite cost, and duration.
- Produces a baseline report with every gate passing and a suite of deterministic, independent failure probes.

- [ ] **Step 1: Write a failing fixture coverage test.**

  Add a test that loads the committed fixture and asserts exactly 20 records per question type, all eight report dimensions are populated, no record contains student, student_answer, candidate_body, or prompt keys, and all global policy metrics pass.

  Run the test. Expected: FAIL because golden-v1.jsonl does not exist.

- [ ] **Step 2: Create the synthetic authorized baseline.**

  Add 120 JSONL records: 20 per question type. Use immutable gpt-5.6-terra, generator-v3, and verification-v5; assign deterministic run IDs, an opaque SHA-256-like fingerprint, fixed seed/parameter snapshot, and finite cost/duration.

  For each 20-record question-type group, use 12 direct accepts, four edited accepts, and four reviewed rejections. Keep all M1/M2 answer results correct, all records schema-valid and grade-aligned, no duplicate/similarity finding, and every published accepted record marked with review evidence. This yields direct acceptance 60% and modified acceptance 100% in every type stratum while retaining rejected-outcome coverage.

- [ ] **Step 3: Add independent end-to-end blocking probes.**

  Parameterize fixture clones that create one wrong M1/M2 answer, one grade mismatch, one exact duplicate, one high-similarity duplicate, one floating model, one unapproved Prompt, and one publication without review evidence. Assert each returns exit 1, writes both report files, and includes only its expected stable violation code plus any directly implied threshold code.

- [ ] **Step 4: Run release-slice verification and commit.**

  Run:

    $env:PYTHONPATH = "$(Join-Path $PWD 'apps\api\src');$(Join-Path $PWD 'services\generator\src');$(Join-Path $PWD 'packages\processor-policy\src');$(Join-Path $PWD 'services\grader\src')"
    python -m pytest apps/api/tests/test_ai_evaluation.py apps/api/tests/test_generation_service.py apps/api/tests/test_ai_question_review.py apps/api/tests/test_question_verification.py -q
    make ai-evaluation
    python -m ruff check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    python -m ruff format --check apps/api/src/edu_grader_api/services/ai_evaluation.py apps/api/tests/test_ai_evaluation.py
    git diff --check
    git add apps/api/tests/fixtures/ai_evaluation/golden-v1.jsonl apps/api/tests/test_ai_evaluation.py
    git commit -m "test: add ai evaluation regression corpus"

  Expected: the baseline command exits 0, six-type fixture coverage passes, every injected failure exits 1, and all verification-related tests pass.

## Delivery Verification

Before reporting completion, run the Task 4 verification block plus:

    git status --short
    git log --oneline -4

Record the exact passed-test count, make ai-evaluation result, artifact locations, and the stable codes observed for each intentional regression in this plan. Do not equate that evidence with isolated-environment acceptance, teacher shadow-mode release, production deployment, or closure of GitHub issue #42.
