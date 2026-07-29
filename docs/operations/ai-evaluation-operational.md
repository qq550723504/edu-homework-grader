# Operational AI evaluation

This runbook turns persisted AI-authoring activity into a de-identified release decision. It complements the repository fixture gate: the fixture gate validates deterministic evaluation behavior, while this workflow evaluates production-shaped generation, validation, teacher-review, and question-version facts at an explicit database watermark.

## Safety properties

The exporter is read-only. It emits one record per generated draft and never exports candidate prompt text, reading passages, rule bodies, teacher email addresses, students, classes, grades, answers, credentials, access tokens, or the system Prompt. It keeps only version identifiers, bounded quality facts, cost and latency observations, an irreversible content fingerprint, and an internal draft/revision key for controlled diagnostics.

A run fails closed when required evidence is missing or contradictory. In particular, it does not silently reuse an older export after a database or mapping failure.

## Protected environment

Create a GitHub Environment named `ai-evaluation-operational`. Restrict it to the protected `main` branch and add required reviewers where appropriate. The workflow runs only from `main` through `workflow_dispatch`; the API additionally rejects tokens unless they identify the exact `ai-evaluation-operational.yml@refs/heads/main` workflow, the immutable repository and owner IDs, public repository visibility, and a GitHub-hosted runner.

Configure these GitHub Environment **variables** (not secrets):

- `OPERATIONAL_EVALUATION_API_URL`: `https://edu.getkr.com/v1/internal/operational-evaluations`.
- `OPERATIONAL_EVALUATION_AUDIENCE`: the audience configured in the production API trust settings.
- `OPERATIONAL_EVALUATION_SPEC_JSON`: the exact export and comparison policy described below.

The workflow has no database URL, HMAC key, kubeconfig, PAT, or cluster credential. It requests a short-lived GitHub OIDC token for each API request. The in-cluster executor receives an independent `operational-evaluation-runtime` Secret containing a `SELECT`-only PostgreSQL URL and the HMAC key; it never receives `edu-grader-runtime`.

Before the first deployment, run `scripts/k8s/bootstrap-operational-evaluation.ps1` from an operator workstation with cluster access. It creates or rotates the database reader, writes the dedicated executor Secret, and adds only the GitHub trust values to `edu-grader-runtime`. It grants `SELECT` only to the exporter’s reviewed table list and fails if PostgreSQL reports any `INSERT`, `UPDATE`, or `DELETE` privilege on that list. It requires the repository ID, owner ID, exact workflow reference, audience, and a digest-pinned API image. It does not print passwords, HMAC keys, database URLs, or OIDC tokens.

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

The GitHub workflow waits for the in-cluster Job, downloads only its signed `report.json`, and uploads that file as `operational-ai-evaluation-<run-id>` for 30 days. The API retains the same signed report plus sanitized run metadata for exactly 30 days; the daily retention Job then deletes the metadata and its per-run callback Secret.

For a local, read-only diagnostic run, the command writes:

- `records.jsonl`: de-identified facts used for the decision;
- `manifest.json`: exporter version, watermark, counts, and deterministic digest;
- `export-issues.json`: stable fail-closed mapping errors;
- `report.json`: a machine-readable signed envelope containing the gates, comparisons, and violations;
- `report.html`: human-readable rendering of the same report.

Operational artifacts are sensitive internal quality evidence even though they exclude student and candidate content. Keep them behind repository/environment access controls and apply the configured retention period. Do not upload local `records.jsonl`, `manifest.json`, or `export-issues.json` to GitHub Actions.

## Interpretation limits

A missing cost or seed is recorded explicitly in the safe `parameters` metadata rather than fabricated. Current cost values are only authoritative when the generation attempt persisted Provider usage data. Teacher-calibrated thresholds, pedagogical adjudication, and shadow/canary rollout decisions remain governed by issue #42; this exporter does not replace those human decisions.

An empty production dataset can complete the transport path, but it is promotion-ineligible because the evidence minimums and required strata are not met. Do not create or promote a generation default merely to prove this operational path.
