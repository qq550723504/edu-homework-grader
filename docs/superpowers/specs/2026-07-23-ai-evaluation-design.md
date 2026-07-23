# AI Question Evaluation Design

**Issue:** #42  
**Status:** Offline release-gate foundation implemented; online evaluation remains open  
**Scope:** Reproducible, de-identified release evidence for AI question generation

## Purpose

The repository now has two complementary quality controls:

1. `make verification-regression` reruns the current production candidate verifier against a deterministic six-type corpus.
2. `make ai-evaluation` evaluates de-identified, teacher-adjudicated outcome snapshots against a versioned release policy.

Neither control promotes a model, Prompt, or curriculum revision. #43 owns promotion, canary routing, rollback, budget controls, and kill switches. #31 owns release-environment end-to-end acceptance.

## Inputs

### Versioned policy

The policy contains:

- approved immutable model IDs;
- approved Prompt versions;
- blocking quality thresholds;
- required question types;
- minimum total evidence;
- minimum evidence per question type; and
- minimum reviewed evidence per question type.

The gate requires M1, M2, E1, E2, E3, and E4. Empty input, a missing type, or insufficient reviewed evidence fails closed with stable violation codes.

### Evaluation records

Each JSONL record is an original or authorised, de-identified outcome snapshot. It contains:

- stable record and run IDs;
- profile, grade, subject, question type, and difficulty band;
- immutable model, Prompt, and validator versions;
- deterministic seed and parameter metadata;
- schema, mathematics-answer, grade-fit, duplicate, and similarity outcomes;
- teacher acceptance, edit, rejection, publication, and review-evidence state;
- cost and duration metadata; and
- an opaque content fingerprint.

Records cannot contain raw student answers, student identity, class identity, raw candidate content, provider credentials, or system Prompt text.

## Cross-field consistency

The release gate rejects contradictory records, including:

- `accepted_after_edit` without a teacher edit;
- `accepted_directly` marked as edited;
- rejected or pending records marked as published;
- rejected records without a rejection category;
- non-rejected records with a rejection category;
- completed reviews without review evidence;
- English records carrying mathematics-answer outcomes; and
- mathematics records without mathematics-answer outcomes.

These are data-quality violations, not ordinary threshold failures.

## Metrics and thresholds

The evaluator calculates global and stratified metrics for:

- structural schema pass rate;
- mathematics answer error rate;
- obvious grade mismatch rate;
- exact or high-similarity rate;
- direct teacher acceptance rate;
- modified-then-accepted rate; and
- publication without teacher review.

Strata are keyed by:

```text
curriculum_profile, grade, subject, question_type,
model_id, prompt_version, validator_version, difficulty_band
```

A populated failing stratum blocks promotion eligibility. An overall average cannot hide a failing grade, profile, or question type.

## Output and exit behavior

`make ai-evaluation` writes:

```text
artifacts/ai-evaluation/report.json
artifacts/ai-evaluation/report.html
```

The command exits zero only when:

- evidence requirements are satisfied;
- record states are internally consistent;
- model and Prompt versions are approved; and
- all global and populated-stratum thresholds pass.

It exits non-zero for empty input, insufficient evidence, inconsistent records, unapproved versions, threshold failures, or publication without review. Diagnostic artifacts are still uploaded by CI.

## CI boundary

The dedicated `AI evaluation gate` workflow:

- installs the repository Python packages;
- runs `make ai-evaluation`; and
- uploads the JSON/HTML report even when the gate fails.

The ordinary CI workflow separately runs the deterministic verification corpus, so the committed snapshot booleans are not the only evidence that current verifier behavior is sound.

## Real Provider boundary

The controlled live integration test uses the production default `generator-v3` contract and requests representative M1, M2, E1, and E4 candidates. It verifies strict Structured Outputs, M1/M2 verification assertions, and E4 reading material. The test remains opt-in because it requires an approved provider credential and immutable model ID.

## Deferred #42 work

This PR does not close all of #42. Follow-up work remains for:

- governed exports from operational generation and review tables;
- teacher-feedback dashboards and post-publication metrics;
- baseline selection and version-to-version regression reports;
- teacher-reviewed calibration of final blocking thresholds;
- shadow/canary evidence integration; and
- pilot-end quality, cost, and rejection analysis.

A passing offline report is required release evidence, but it is not proof of production readiness or school-pilot approval.
