# AI Question Evaluation Design

**Issue:** #42
**Status:** approved design; implementation has not started
**Scope:** release-candidate quality evidence for AI question generation

## Problem

The repository has deterministic candidate verification and a mature English grader calibration utility. Neither produces a single, versioned release gate for generated questions. The existing calibration report only summarizes E1--E4 grading decisions and cannot show generation correctness, curriculum fit, similarity, teacher outcomes, or whether a candidate model/Prompt is eligible to become the default.

The evaluation gate must be reproducible in CI, must not include real student answers or other minor personal data, and must not require a live operational database. A report that merely renders successfully is insufficient: known bad data must cause a non-zero command exit.

## Chosen Architecture

`make ai-evaluation` will run an offline evaluator over a versioned JSONL golden dataset and a versioned policy file. It writes:

```text
artifacts/ai-evaluation/report.json
artifacts/ai-evaluation/report.html
```

The evaluator is a small, pure Python module in the Core API package. Its input contract is a snapshot of generation and teacher-review facts rather than a direct database reader. This makes the same dataset usable in CI, locally, and for exported pilot feedback while keeping data selection and access control outside the release gate.

Existing `edu_grader.calibration` remains the owner of E1--E4 grader calibration. The new evaluator consumes the same kind of teacher-adjudicated facts and may include its summary in the report; it does not duplicate the grader's score comparison logic.

Direct operational reporting, dashboard filters, tenant permissions, canary routing, and changing the default model are not part of this slice. #43 owns those control-plane actions. This evaluator provides only reproducible evidence and `promotion_eligible` advice.

## Inputs

### Evaluation policy

The committed policy file has a policy identifier and these versioned values:

- approved immutable model IDs;
- approved Prompt versions;
- blocking thresholds;
- optional minimum sample size for a release decision.

The first policy version carries these thresholds, as configuration rather than hard-coded evaluator constants:

| Metric | Release condition |
| --- | ---: |
| Structural schema pass rate | >= 98% |
| Mathematics answer error rate | <= 0.5% |
| Obvious grade mismatch rate | <= 2% |
| Exact or high-similarity rate | <= 3% |
| Teacher direct-accept rate | >= 60% |
| Teacher modified-then-accept rate | >= 85% |
| Published without teacher review | 0 |

### Golden evaluation record

Each JSONL record is original or authorized evaluation data and carries one candidate outcome. It contains:

- stable record and run IDs;
- curriculum profile, grade, subject, question type (`M1`, `M2`, `E1`--`E4`), and difficulty band;
- immutable model ID, Prompt version, validator version, and deterministic seed/parameter snapshot;
- structural-schema result, mathematics-answer result when applicable, grade-fit result, and duplicate/similarity result;
- teacher outcome (`accepted_directly`, `accepted_after_edit`, `rejected`, or `pending_review`) plus a structured rejection category when present;
- publication state, review evidence flag, cost, and end-to-end duration.

The record stores no raw student answer, student identity, or raw candidate body. For repeatability it uses an opaque content fingerprint and stable finding/rejection codes. The generated-question tables already provide the source facts for future exports: job/attempt model and Prompt snapshots, draft revision/fingerprints, validation runs, and review decisions.

## Evaluation Semantics

The evaluator validates every input record before calculating metrics. An invalid record, duplicate record ID, unknown question type, non-immutable model, or missing version field is a data-quality violation and blocks promotion. A floating or otherwise unapproved model, and an unapproved Prompt version, each produce a stable version-approval violation.

For each population and stratum, the evaluator computes numerator, denominator, rate, threshold, and pass/fail state. Zero denominators are reported as `not_applicable`; required global metrics with no evidence block promotion rather than silently passing. Exact duplicates and similarity matches share one denominator (evaluated candidates) and one release metric; a record is counted at most once in that metric.

Teacher metrics are intentionally separated:

- direct acceptance is accepted without a teacher edit divided by reviewed candidates;
- modified acceptance is accepted after an edit divided by all candidates that received a teacher edit;
- publication without teacher review is the count of published records whose required review evidence is absent.

`pending_review` never counts as accepted or as a reviewed publication. This preserves the E3/E4 teacher-review invariant established by #83.

The report includes a global summary and an explicit strata table keyed by:

```text
curriculum_profile, grade, subject, question_type,
model_id, prompt_version, validator_version, difficulty_band
```

It also reports rejection categories, cost per final accepted question, and end-to-end duration for observed records. A stratum does not replace the global gate: every failing populated stratum is a release violation, so an overall average cannot hide a profile, grade, or question-type regression.

## Output and Exit Contract

`report.json` is the machine-readable source of truth. It contains input and policy identifiers, aggregate metrics, strata, stable violations, and:

```json
{
  "promotion_eligible": false
}
```

when any structural, threshold, data-quality, or version-approval violation exists. It contains `true` only when all required evidence passes the policy. `report.html` is a deterministic, escaped presentation of the same report; it introduces no additional logic.

The command writes both artifacts before returning. It exits zero only when `promotion_eligible` is true and exits non-zero otherwise. Consequently CI retains diagnostic artifacts even for an expected blocking failure.

The evaluator does not promote anything. #43 must require a passing, identified report before a canary candidate is moved to `active`.

## Regression Evidence

The repository will ship an authorized, synthetic golden fixture covering all six question types and their profile/grade/subject/difficulty strata. Tests will demonstrate that the baseline passes and that each of these independent mutations causes a non-zero evaluation result with a stable violation code:

1. a wrong M1/M2 answer;
2. an out-of-curriculum or age-inappropriate item;
3. an exact or high-similarity duplicate;
4. a floating or policy-unapproved model ID;
5. a policy-unapproved Prompt version;
6. publication without teacher review.

Tests also assert that the JSON report contains every required stratum key, the HTML output is produced, and the report exposes enough counts to compare two versioned runs without relying on an overall average.

## Acceptance Boundaries

This slice is complete when the single Make target produces both artifacts from a deterministic dataset, passing baseline results are reproducible, and all listed bad-data probes fail in CI. It is not proof of isolated release environment acceptance, teacher shadow-mode approval, production-school deployment, or a replacement for #43 governance controls.

