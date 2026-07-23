# Operational AI evaluation

This runbook turns persisted AI-authoring activity into a de-identified release decision. It complements the repository fixture gate: the fixture gate validates deterministic evaluation behavior, while this workflow evaluates production-shaped generation, validation, teacher-review, and question-version facts at an explicit database watermark.

## Safety properties

The exporter is read-only. It emits one record per generated draft and never exports candidate prompt text, reading passages, rule bodies, teacher email addresses, students, classes, grades, answers, credentials, access tokens, or the system Prompt. It keeps only version identifiers, bounded quality facts, cost and latency observations, an irreversible content fingerprint, and an internal draft/revision key for controlled diagnostics.

A run fails closed when required evidence is missing or contradictory. In particular, it does not silently reuse an older export after a database or mapping failure.

## Protected environment

Create a GitHub Environment named `ai-evaluation-operational`. Restrict it to approved release branches and add required reviewers where appropriate.

Configure:

- Secret `DATABASE_URL`: a read-only PostgreSQL connection scoped to the evaluation tenant or replica.
- Secret or variable `OPERATIONAL_EVALUATION_SPEC_JSON`: the exact export and comparison policy described below.

Do not use an application owner credential. The database role needs `SELECT` only on curriculum, generation, validation, review, governance, question, and grading-policy tables used by the exporter.

## Specification

The specification requires an exact tenant, a timezone-aware watermark, an explicit baseline, and an explicit candidate. Neither `latest` nor ordering-based baseline selection is supported.

```json
{
  "spec_id": "teacher-shadow-2026-08-rc1",
  "export": {
    "tenant_id": "00000000-0000-0000-0000-000000000000",
    "run_id": "teacher-shadow-2026-08-rc1",
    "watermark": "2026-08-15T00:00:00Z"
  },
  "baseline": {
    "provider_name": "openai",
    "model_id": "approved-immutable-baseline-model-id",
    "prompt_version": "generator-v3",
    "validator_version": "verification-v5"
  },
  "candidate": {
    "provider_name": "openai",
    "model_id": "approved-immutable-candidate-model-id",
    "prompt_version": "generator-v4",
    "validator_version": "verification-v6"
  },
  "gate_policy": {
    "policy_id": "teacher-shadow-policy-v1",
    "approved_model_ids": [
      "approved-immutable-baseline-model-id",
      "approved-immutable-candidate-model-id"
    ],
    "approved_prompt_versions": ["generator-v3", "generator-v4"],
    "thresholds": {
      "schema_pass_rate_min": 0.98,
      "math_answer_error_rate_max": 0.005,
      "grade_mismatch_rate_max": 0.02,
      "duplicate_or_similarity_rate_max": 0.03,
      "teacher_direct_accept_rate_min": 0.60,
      "teacher_modified_accept_rate_min": 0.85,
      "published_without_teacher_review_max": 0
    },
    "evidence_requirements": {
      "required_question_types": ["M1", "M2", "E1", "E2", "E3", "E4"],
      "minimum_total_records": 120,
      "minimum_records_per_question_type": 20,
      "minimum_reviewed_records_per_question_type": 20
    }
  },
  "max_metric_regression": {
    "schema_pass_rate": 0,
    "math_answer_error_rate": 0,
    "grade_mismatch_rate": 0,
    "duplicate_or_similarity_rate": 0,
    "teacher_direct_accept_rate": 0.02,
    "teacher_modified_accept_rate": 0.02,
    "published_without_teacher_review": 0
  },
  "stratum_fields": [
    "curriculum_profile",
    "grade",
    "subject",
    "question_type",
    "difficulty_band"
  ]
}
```

The baseline model, Prompt, and Provider must have an effective governance state of `active`. The candidate may be `active` or explicitly enrolled in `canary`. Missing governance records do not count as release approval.

## Running locally

Use a read-only database URL and keep the specification outside source control when it contains tenant-specific operational configuration.

```bash
DATABASE_URL='postgresql+psycopg://readonly:...@host/db' \
make ai-evaluation-operational \
  SPEC=/secure/path/operational-spec.json \
  OUTPUT=artifacts/ai-evaluation-operational
```

Exit code `0` means both versions meet their individual gates, governance approval is present, required strata are represented, and the candidate stays within the configured regression budget. Exit code `1` means the candidate must not be promoted.

## Artifacts

The command writes:

- `records.jsonl`: de-identified facts used for the decision;
- `manifest.json`: exporter version, watermark, counts, and deterministic digest;
- `export-issues.json`: stable fail-closed mapping errors;
- `report.json`: machine-readable gates, comparisons, and violations;
- `report.html`: human-readable rendering of the same report.

Operational artifacts are sensitive internal quality evidence even though they exclude student and candidate content. Keep them behind repository/environment access controls and apply the configured retention period.

## Interpretation limits

A missing cost or seed is recorded explicitly in the safe `parameters` metadata rather than fabricated. Current cost values are only authoritative when the generation attempt persisted Provider usage data. Teacher-calibrated thresholds, pedagogical adjudication, and shadow/canary rollout decisions remain governed by issue #42; this exporter does not replace those human decisions.
