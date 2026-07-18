# Student Assignments, Offline Drafts, and Idempotent Submission Design

## Goal

Implement Issue #4: a mobile-first student workflow that lists assigned work, preserves answer drafts offline, synchronizes safely, and submits exactly once. The slice includes the smallest teacher-facing API needed to create and publish an assignment; it deliberately does not add a teacher assignment-management interface.

## Scope

This slice builds the assignment and student-attempt boundary that was intentionally deferred by Issue #3. It uses only already-published question versions, so a student always receives the exact prompt and rule version selected by the teacher. It does not grade answers, expose scores, implement corrections, or publish results; Issues #5 through #7 add those responsibilities.

## Selected approach

Use Dexie as the Nuxt client's IndexedDB wrapper and maintain an explicit per-student outbox. Dexie is a mature IndexedDB abstraction with transactions, schema upgrades, and indexed queries; this avoids implementing browser persistence and retry mechanics from scratch.

The API remains authoritative. The local database provides immediate durable draft storage while offline, but never resolves conflicts by last-writer-wins. Each answer mutation carries the server version last observed by that browser. A stale write receives a conflict response with the current server draft, and the UI marks the answer as needing the student's decision.

Use a durable PostgreSQL submission receipt rather than a Redis-only response cache. A unique receipt scoped to the student and `Idempotency-Key` survives process restarts and returns the original successful result when a browser retries after a lost response. The idempotency key must be a UUID generated once for a submission attempt and retained locally until the response is acknowledged.

## Data model

All new rows are tenant-scoped, use application-generated UUIDs, and are accessed only through a verified current principal.

### `assignments`

An assignment targets one class: `id`, `tenant_id`, `class_id`, `created_by_user_id`, `title`, `subject`, `due_at`, `submission_rule_json`, `status`, `created_at`, and `published_at`. Status is `draft` or `published`. A teacher may create or publish only assignments for a class in `class_teachers` within their tenant.

### `assignment_items`

An ordered immutable selection of published content: `id`, `assignment_id`, `question_version_id`, `position`, and `created_at`. `(assignment_id, position)` is unique. Creation verifies that the referenced question version is published and belongs to the teacher's tenant. Items cannot be added, removed, or reordered after publication.

### `student_attempts`

The student's current work for an assignment: `id`, `tenant_id`, `assignment_id`, `student_id`, `attempt_number`, `status`, `started_at`, and `submitted_at`. Status is `draft` or `submitted`. A database uniqueness constraint allows one initial attempt for `(assignment_id, student_id, attempt_number = 1)` in this slice. A future correction creates a later attempt number rather than modifying this record.

### `attempt_answers`

One current answer per assignment item: `id`, `attempt_id`, `assignment_item_id`, `answer_json`, `version`, `updated_at`. `(attempt_id, assignment_item_id)` is unique. The server creates a version-1 row on the first save and increments it atomically for every accepted update. A submitted attempt rejects all answer changes.

### `submission_receipts`

The durable idempotency record: `id`, `tenant_id`, `student_id`, `assignment_id`, `idempotency_key`, `request_fingerprint`, `response_status`, `response_json`, and `created_at`. `(student_id, idempotency_key)` is unique. Reusing a key for another assignment or a differing request fingerprint returns `409`; retrying the same operation returns the recorded status and body without creating a second submission.

Teacher assignment lifecycle events and student submission events append privacy-safe audit metadata. Audit records contain identifiers, versions, and state transitions only; they never include answers, tokens, or identity claims.

## Authorization and lifecycle

1. An assigned teacher creates an assignment in `draft`, selects published question versions, and publishes it.
2. A student who is enrolled in the assignment's class can list and open the published assignment. Other tenants, non-enrolled students, and non-assigned teachers receive `404`.
3. Opening an assignment creates or returns the student's draft attempt. The detail response includes the frozen assignment item sequence, existing answers, versions, due time, and submission status.
4. The browser saves an answer locally before queuing the versioned API mutation. The outbox coalesces later edits of the same answer but keeps the original server version until that mutation succeeds.
5. The sync loop performs queued mutations in order while online. It retries transient network failures with bounded backoff. Page navigation, `visibilitychange` to hidden, and the `online` event trigger an immediate sync attempt; they do not claim delivery if the browser stops it.
6. On an optimistic-lock conflict, the client retains both its local value and the returned server value, stops that item's retries, and shows a conflict status. It never silently overwrites the server value.
7. Submission is enabled only while online and after all current outbox entries have synchronized. The client generates and retains one UUID `Idempotency-Key`, then posts the submission request. The API atomically verifies the draft attempt, creates the receipt, marks the attempt submitted, and records the original response.
8. Repeated clicks or a retry after a lost response use the same key and receive the first result. After submission, every answer-save operation returns `409`; future correction work creates a new attempt rather than altering the submitted one.

## HTTP contract

### Minimal teacher APIs

- `POST /v1/assignments` creates a teacher-owned draft assignment for a class the teacher is assigned to.
- `POST /v1/assignments/{assignment_id}/items` adds a published question version to a draft assignment at a unique position.
- `POST /v1/assignments/{assignment_id}/publish` validates that the assignment has at least one item and makes it visible to enrolled students.

### Student APIs

- `GET /v1/student/assignments` returns tenant-local assignments grouped as `pending`, `correction_required`, and `completed`. This slice returns an empty correction group until Issue #7 creates correction attempts.
- `GET /v1/student/assignments/{assignment_id}` returns the frozen assignment metadata, ordered question snapshots required for answering, the draft attempt, answer versions, and summary progress.
- `PUT /v1/student/attempts/{attempt_id}/answers/{assignment_item_id}` accepts `answer` and required `version`. It returns the persisted answer and next version, or `409` with the latest server answer and version.
- `POST /v1/student/assignments/{assignment_id}/submit` requires the `Idempotency-Key` header. It returns the original `submitted` result for an identical retry, `400` for a missing or malformed key, and `409` when unsynchronized/conflicting state or a previously submitted attempt prevents submission.

No student endpoint returns grading policy internals, standard answers, test cases, unpublished content, or unissued grades.

## Web client

The student home page reads the list API and renders pending, correction-required, and completed sections. The assignment page displays subject, due time, question count, progress, submission rule, numbered question navigation, previous/next controls, and an unanswered-item warning before submission.

The client-only Dexie database stores `drafts` and `outbox` records keyed by tenant, user, attempt, and assignment item. The browser clears the current user's local records on logout; records are never shared across user identities. The UI reports one of `saved_locally`, `syncing`, `synced`, `offline`, or `conflict` for each assignment. It does not promise background completion when browser lifecycle APIs terminate an asynchronous request.

## Testing

Tests are written before implementation.

Backend pytest coverage includes:

- tenant, enrolled-student, and assigned-teacher boundaries for every assignment and attempt endpoint;
- rejection of draft items that are unpublished, foreign-tenant, or added after publication;
- assignment list grouping and frozen question-version references;
- first answer save, atomic version increment, stale-version `409`, and rejection after submission;
- missing/malformed idempotency keys, repeat clicks, lost-response retries, and same-key reuse with a different request;
- one submitted attempt and one submission audit event under concurrent requests.

Web tests use Vitest with `fake-indexeddb` for Dexie behavior and cover immediate local persistence, outbox coalescing, offline retention, reconnect synchronization, conflict visibility, navigation-triggered synchronization, and reuse of a submission key through retries. A browser-level student-flow test covers unanswered warning, disabled offline submission, and duplicate-click submission behavior.

## Acceptance mapping

The design provides the three student list groups, assignment detail and question navigation, IndexedDB-backed drafts, throttled synchronization triggers, visible offline status, server optimistic locking, online idempotent submission, immutable submitted attempts, and automated coverage for offline recovery, duplicate submission, and version conflicts. It also fills the missing assignment publication boundary needed for Issue #4 without expanding into teacher management UI or grading/review work.
