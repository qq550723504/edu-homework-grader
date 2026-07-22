# Atomic AI Candidate Batch Acceptance Design

**Issues:** #40, #41
**Status:** Approved for implementation
**Scope:** API/service gate only; a batch-selection UI is deferred.

## Goal

Allow a teacher to accept several candidates from one generation job without weakening the
single-candidate review boundary. A batch is all-or-nothing: no blocked candidate can create a
question draft, every warning needs an explicit per-candidate acknowledgement, and a retry of the
same idempotency key returns the original result.

## Boundary

- The route accepts only IDs and expected revision numbers belonging to one authorized job.
- The service reuses `accept_review_draft`; it does not duplicate candidate-to-QuestionVersion
  conversion, validation checks, or audit-event semantics.
- A batch stores its immutable request digest and decision references. This is required to detect a
  duplicate whole request, including a retry whose item set differs from the original request.
- Validation and teacher state are locked/preflighted before any QuestionVersion is created.
- `blocked`, stale, missing, unauthorized, or unacknowledged-warning items fail the complete
  transaction. No partial acceptance is returned.
- The endpoint never publishes a QuestionVersion. Accepted versions remain `draft`.

## API

`POST /v1/ai-question-generation/jobs/{job_id}/bulk-accept`

The body has 1--20 unique items:

```json
{
  "items": [
    {"draft_id": "uuid", "expected_revision_number": 3, "confirm_warnings": false}
  ]
}
```

`Idempotency-Key` is required. The response contains the accepted draft and QuestionVersion IDs in
the request order. Reusing the key with a changed body returns a stable conflict code.

## Persistence and transaction

`generation_batch_acceptances` records tenant, job, actor, idempotency key, request digest, and
creation time. Its child rows record each accepted review decision in request order. Both tables are
append-only. The service locks/replays the batch record first, then locks and preflights item drafts
in a stable order before calling the existing single-candidate service inside one transaction. A
unique-key collision re-reads the winning committed batch and returns its replay instead of a
spurious write conflict.

## Tests

- passed candidates create draft QuestionVersions in request order;
- a blocked item, stale revision, or missing warning acknowledgement rolls back every item;
- a retry returns the original accepted IDs and creates no additional QuestionVersions;
- a changed body with the same key conflicts;
- job/tenant/teacher isolation and safe audit metadata hold.
