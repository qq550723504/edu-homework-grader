# Data Retention, Deletion Requests, and Preservation Holds

## Goal

Implement the next Issue #8 compliance slice: a school-admin-operated deletion-request workflow that immediately prevents new student processing, honors preservation holds and retention deadlines, and makes cleanup a controlled, auditable action.

## Scope and exclusions

This slice adds only the platform-side workflow. A tenant administrator enters a request only after the school has verified the request through its own approved process.

The platform stores no requester name, guardian contact detail, identity document, request form, or evidence file. It stores only the affected internal student UUID, a short operational reason, lifecycle timestamps, actors, and a retention deadline.

This slice does not add a student self-service request form, data export, backup erasure, automatic background scheduling, or immediate cascading deletion. Existing audit records remain for their three-year retention period.

## Alternatives considered

1. **Request-centric workflow with preservation hold and controlled cleanup (selected).** One student-scoped request provides a single enforcement point and an auditable state machine. It avoids missing one of the many relational tables that contain a student attempt or review trail.
2. **Per-table lifecycle flags.** This permits more granular cleanup but spreads the same policy through every data table and makes cross-table correctness difficult to prove.
3. **Immediate cascading deletion.** This is incompatible with preservation obligations and would destroy review evidence and the append-only audit ledger.

## Data model

Add `privacy_requests`, scoped to one student:

| Field | Meaning |
| --- | --- |
| `id` | Internal UUID request identifier |
| `tenant_id`, `student_id` | Tenant and target student internal UUIDs |
| `request_type` | Initially only `erasure` |
| `status` | `requested`, `legal_hold`, `approved`, `rejected`, or `completed` |
| `reason` | Short operational reason; no contact or evidence data |
| `requested_by_user_id`, `decided_by_user_id` | Administrator actors |
| `requested_at`, `decided_at`, `eligible_for_deletion_at`, `completed_at` | Lifecycle timestamps |
| `hold_reason` | Short preservation reason while the request is held |
| `version` | Optimistic-lock version |

Only one active request (`requested`, `legal_hold`, or `approved`) may exist for a student. The database must enforce this so concurrent administrator actions cannot create contradictory processing restrictions.

## Workflow and enforcement

1. An administrator creates an `erasure` request. The request immediately restricts new student processing.
2. An administrator can place the request on `legal_hold`, recording the short reason. Hold prevents approval and cleanup.
3. An administrator can approve a non-held request, setting `eligible_for_deletion_at` from the applicable policy. They can alternatively reject it, which removes the restriction.
4. A shared student-processing dependency checks the active request before assignment reads, saves, submissions, correction submissions, and appeals. Active requests return `403 data processing restricted` before any grading or data mutation service runs.
5. A privileged administrative command lists eligible requests by default. `--execute` is required to perform the irreversible cleanup. It rechecks status, deadline, and absence of a hold in the same transaction, then removes only the student-linked operational records permitted by this slice and marks the request `completed`.

For the initial cleanup boundary, the command deletes the student-owned draft and submitted attempt graph, answers, grading runs and signals, review tasks and decisions, appeals, correction links, grade publications, submission receipts, enrollment records, guardian-consent record, and the student identity record. It does not delete assignments, questions, grading policies, tenant records, or audit records. Every cleanup outcome is recorded in the audit ledger without answer contents or personal identifiers.

## API and audit boundary

Administrative routes are tenant-scoped and require `admin`:

- `POST /v1/admin/students/{student_id}/privacy-requests`
- `POST /v1/admin/privacy-requests/{request_id}/hold`
- `POST /v1/admin/privacy-requests/{request_id}/approve`
- `POST /v1/admin/privacy-requests/{request_id}/reject`

All state mutations require the current `version`. Events are `privacy_request.created`, `privacy_request.held`, `privacy_request.approved`, `privacy_request.rejected`, and `privacy_request.completed`. Metadata contains only request type, status, version, and policy deadline.

## Failure handling

- Other-tenant students and requests return `404`.
- Invalid state transitions and missing required reasons return `422`.
- Stale versions and duplicate active requests return `409`.
- Cleanup that discovers a hold, non-approved state, or a future deadline leaves all records unchanged and reports the request as skipped.
- Audit failures roll back the administrative transition or cleanup transaction.

## Verification

Tests cover database uniqueness of active requests, role and tenant isolation, all state transitions and optimistic locking, processing-gate coverage, preservation-hold refusal, cleanup dry-run and execute behavior, foreign-key-safe deletion order, and audit-chain verification. PostgreSQL migration tests exercise the partial unique index and the cleanup transaction.

`docs/data-inventory.md` and `SECURITY.md` will be updated with the request record, active restriction behavior, preservation hold, and explicit cleanup operation.
