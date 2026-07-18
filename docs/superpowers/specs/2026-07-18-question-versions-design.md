# Question Versions and Grading Policies Design

## Goal

Implement Issue #3: tenant-scoped, traceable question authoring with immutable published versions, platform-owned grading-policy schemas, mandatory pre-publish test cases, and auditable test runs.

## Scope

This slice establishes question, rule, and test contracts only. It does not create assignments, accept student submissions, or publish grades. The existing Grader service remains the only deterministic grading implementation.

## Selected approach

The API stores a policy instance as JSON but validates it against a platform-maintained JSON Schema selected by question type and policy version. Teachers cannot upload an arbitrary schema. This retains flexible mathematics and English configuration without allowing malformed rules to enter the grading pipeline.

Use the mature jsonschema library with an explicit Draft 2020-12 validator. Validation responses expose a JSON path and message, not raw implementation exceptions.

## Data model

### questions

Tenant-scoped logical question: id, tenant_id, created_by_user_id, title, current_draft_version_id, current_published_version_id, created_at, updated_at.

### question_versions

Immutable version snapshot: id, question_id, version_number, status, prompt, question_type, grading_policy_id, rule_json, created_by_user_id, created_at, published_by_user_id, published_at.

Status is draft, published, or archived. A unique constraint on question_id and version_number orders versions. A published or archived version has no update route. Editing a draft creates a new version instead of mutating an existing snapshot.

### grading_policies

Platform-owned policy registry: id, question_type, policy_version, json_schema, created_at, retired_at. Question versions refer only to an active policy whose question type matches the version. The first policy set covers M1 numeric, M2 expression, E1 exact, and E4 assisted short-answer foundations; later issues extend policy content, not the core version lifecycle.

### question_test_cases

Version-bound, immutable when published: id, question_version_id, category, answer_json, expected_decision, expected_score, expected_evidence_json, created_at. Each pre-publish suite requires correct, incorrect, empty, and boundary categories. M2 additionally requires invalid_ast. E4 expected decisions are needs_review.

### question_test_runs and question_test_case_runs

A run stores question_version_id, grader_version, trigger, status, started_at, finished_at, and failure summary. Each case result stores decision, score, evidence JSON, pass/fail, and error detail. A publication checks the latest completed full run for the exact version.

## Lifecycle and permissions

1. A teacher creates a question and draft version in their tenant.
2. The author edits by producing a successor draft version. Existing versions never change.
3. The author adds test cases and runs the complete suite against the Grader service.
4. Publish succeeds only when the latest full run for that exact version passes every required category and case.
5. Published versions are frozen. A later edit creates a successor draft; future assignments reference the published version ID, never the mutable question ID.
6. Teachers can edit only drafts they authored. Tenant teachers may read published versions to reuse them. All state changes append an audit log record.

Tenant and ownership lookup failures return 404. Invalid JSON policy or test-case shape returns 422 with the JSON pointer and human-readable reason. An incomplete, failed, or stale run returns 409 from publish. Grader exceptions create a grading_error result and block publication.

## HTTP contract

- POST /v1/questions creates a question and its first draft version.
- POST /v1/questions/{question_id}/versions creates a successor draft from a readable version.
- PUT /v1/question-versions/{version_id} creates the successor snapshot for an authored draft.
- POST /v1/question-versions/{version_id}/test-cases writes a draft-only case.
- POST /v1/question-versions/{version_id}/test-runs runs every case and saves individual results.
- POST /v1/question-versions/{version_id}/publish publishes the exact draft only after a passing complete run.

The Grader request contains only question type, rule JSON, answer JSON, and version identifiers. It never receives a user, tenant, school ID, or access token.

## Testing

Tests are written first and cover:

- version numbering, immutable published rows, and historical version references;
- policy-schema mismatch and accurate JSON-path errors;
- author, tenant, and published-read authorization boundaries;
- complete/failed/stale suite publication gating;
- per-case persistence of result, evidence, grader version, and grader errors;
- all required test-case categories for each supported question type;
- audit events for creation, versioning, test runs, and publication.

## Acceptance mapping

The design provides the Issue #3 models, immutable version semantics, mathematics and English rule configuration, mandatory correct/incorrect/empty/boundary cases, pre-publish execution with per-case feedback, stable historical references, and auditable rule changes.

