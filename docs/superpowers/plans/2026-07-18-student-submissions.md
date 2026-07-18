# Student Assignments and Submission Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Deliver Issue #4's student assignment list, offline-first drafts, optimistic answer saving, and idempotent online submission, including the minimum API needed to publish an assignment.

**Architecture:** Extend the existing SQLAlchemy/Alembic API with immutable assignment item selections, one versioned student attempt, and durable submission receipts. The Nuxt client writes drafts and an ordered outbox to Dexie before synchronizing to the API; conflicts remain visible instead of applying a last-writer-wins overwrite.

**Tech Stack:** FastAPI 0.139, SQLAlchemy 2, Alembic, PostgreSQL/SQLite test database, Nuxt 4.4, Vue 3, Dexie 4, Vitest, fake-indexeddb.

## Global Constraints

- Every new database row is tenant-scoped and every API lookup is constrained by the verified CurrentPrincipal tenant and role.
- Teachers create and publish only for classes in class_teachers; students access only published work for their enrollments.
- Assignment items reference only a published QuestionVersion and become immutable at assignment publication.
- Submitted attempts are immutable; correction is deferred to Issue #7 as a new attempt.
- Answer writes use an integer version and return a conflict rather than silently overwriting a different version.
- Idempotency-Key is required, UUID-shaped, persisted per student, and safely replays only the identical submission result.
- Never put answers, access tokens, or identity claims in audit metadata or routine logs.
- All new behavior is test-first; use ruff format and ruff check before each commit.

## File Structure

- apps/api/src/edu_grader_api/models.py: assignment, attempt, answer, receipt ORM models and status enums.
- apps/api/alembic/versions/0003_student_assignments.py: tables, foreign keys, uniqueness constraints, and indexes.
- apps/api/src/edu_grader_api/services/assignments.py: tenant-safe lifecycle and persistence operations.
- apps/api/src/edu_grader_api/routers/assignments.py: minimal teacher and student HTTP contract.
- apps/api/tests/test_assignment_models.py and test_assignments.py: model, authorization, mutation, and idempotency coverage.
- apps/web/app/lib/drafts.ts: Dexie tables and outbox transitions.
- apps/web/app/composables/useAssignmentSync.ts: browser-only API synchronizer.
- apps/web/app/pages/student/index.vue and student/assignments/[assignmentId].vue: list and answering UX.
- apps/web/tests/drafts.test.ts and assignment-sync.test.ts: browser-storage and synchronizer tests.
- apps/web/package.json and vitest.config.ts: Dexie/Vitest dependencies and test command.

---

### Task 1: Add durable assignment and attempt persistence

**Files:**
- Modify: apps/api/src/edu_grader_api/models.py
- Create: apps/api/alembic/versions/0003_student_assignments.py
- Create: apps/api/tests/test_assignment_models.py

**Interfaces:**
- Consumes: Classroom, ClassTeacher, Enrollment, QuestionVersion, User, AuditLog, and utc_now from models.py.
- Produces: AssignmentStatus, AttemptStatus, Assignment, AssignmentItem, StudentAttempt, AttemptAnswer, and SubmissionReceipt.

- [ ] **Step 1: Write failing model tests**

~~~python
def test_assignment_item_position_is_unique() -> None:
    session.add_all([
        AssignmentItem(assignment=assignment, question_version=published_version, position=1),
        AssignmentItem(assignment=assignment, question_version=published_version, position=1),
    ])
    with pytest.raises(IntegrityError):
        session.commit()

def test_answer_and_submission_receipt_have_scoped_unique_keys() -> None:
    session.add_all([
        AttemptAnswer(attempt=attempt, assignment_item=item, answer_json={"value": "5"}, version=1),
        AttemptAnswer(attempt=attempt, assignment_item=item, answer_json={"value": "6"}, version=1),
    ])
    with pytest.raises(IntegrityError):
        session.commit()
~~~

- [ ] **Step 2: Run the test and verify RED**

Run: python -m pytest apps/api/tests/test_assignment_models.py -q

Expected: FAIL during collection because assignment symbols do not exist.

- [ ] **Step 3: Implement models and migration**

Add enums:

~~~python
class AssignmentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"

class AttemptStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
~~~

Add these exact ownership fields:
- Assignment: id, tenant_id, class_id, created_by_user_id, title, subject, due_at, submission_rule_json, status, created_at, published_at.
- AssignmentItem: id, assignment_id, question_version_id, position, created_at; unique assignment_id/position.
- StudentAttempt: id, tenant_id, assignment_id, student_id, attempt_number, status, started_at, submitted_at; unique assignment_id/student_id/attempt_number.
- AttemptAnswer: id, attempt_id, assignment_item_id, answer_json, version, updated_at; unique attempt_id/assignment_item_id.
- SubmissionReceipt: id, tenant_id, student_id, assignment_id, idempotency_key, request_fingerprint, response_status, response_json, created_at; unique student_id/idempotency_key.

Create Alembic revision 0003 from 0002. It must declare all foreign keys, the listed unique constraints, and indexes for assignment tenant/class/status and attempt student/assignment. Use relationships with back_populates and do not add cascade delete behavior to submitted work.

- [ ] **Step 4: Run focused model checks and verify GREEN**

Run:
~~~powershell
python -m pytest apps/api/tests/test_assignment_models.py apps/api/tests/test_question_models.py -q
python -m ruff check apps/api
~~~

Expected: PASS; duplicate positions, answers, and receipt keys raise IntegrityError.

- [ ] **Step 5: Commit the schema slice**

~~~powershell
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0003_student_assignments.py apps/api/tests/test_assignment_models.py
git commit -m "feat(api): add assignment persistence"
~~~

### Task 2: Create and publish teacher-owned assignments

**Files:**
- Create: apps/api/src/edu_grader_api/services/assignments.py
- Create: apps/api/src/edu_grader_api/routers/assignments.py
- Modify: apps/api/src/edu_grader_api/main.py
- Create: apps/api/tests/test_assignments.py

**Interfaces:**
- Consumes: Task 1 models and require_role(Role.TEACHER).
- Produces: create_assignment, add_assignment_item, publish_assignment and teacher endpoints.

- [ ] **Step 1: Write failing teacher route tests**

~~~python
def test_assigned_teacher_can_publish_a_versioned_assignment(client, session) -> None:
    created = client.post("/v1/assignments", headers=authorize(client, teacher), json=payload)
    assert created.status_code == 201
    assignment_id = created.json()["id"]
    item = client.post(f"/v1/assignments/{assignment_id}/items", headers=authorize(client, teacher),
                       json={"question_version_id": str(published_version.id), "position": 1})
    assert item.status_code == 201
    assert client.post(f"/v1/assignments/{assignment_id}/publish",
                       headers=authorize(client, teacher)).status_code == 200

def test_unassigned_teacher_and_draft_question_are_rejected(client, session) -> None:
    assert client.post("/v1/assignments", headers=authorize(client, unassigned_teacher),
                       json=payload).status_code == 404
    assert client.post(f"/v1/assignments/{assignment.id}/items", headers=authorize(client, teacher),
                       json={"question_version_id": str(draft_version.id), "position": 1}).status_code == 422
~~~

- [ ] **Step 2: Run the tests and verify RED**

Run: python -m pytest apps/api/tests/test_assignments.py -q

Expected: FAIL because the router and services do not exist.

- [ ] **Step 3: Implement lifecycle services and thin routes**

Implement:

~~~python
def create_assignment(session: Session, *, tenant_id: UUID, teacher_id: UUID,
                      class_id: UUID, title: str, subject: str, due_at: datetime,
                      submission_rule_json: dict[str, object]) -> Assignment: ...
def add_assignment_item(session: Session, assignment: Assignment, *, teacher_id: UUID,
                        question_version_id: UUID, position: int) -> AssignmentItem: ...
def publish_assignment(session: Session, assignment: Assignment, *, teacher_id: UUID) -> Assignment: ...
~~~

All three require that the teacher is assigned to the tenant-local class. add_assignment_item allows only a draft Assignment and a tenant-local published QuestionVersion. publish_assignment requires at least one item, changes status once, and no mutation route permits an item change after it. Append assignment.created, assignment.item_added, and assignment.published audits whose metadata contains IDs and positions only.

Expose POST /v1/assignments, POST /v1/assignments/{assignment_id}/items, and POST /v1/assignments/{assignment_id}/publish. Use the questions router's transaction pattern: rollback, with session.begin(), then map access failure to 404, state conflict to 409, and input failure to 422.

- [ ] **Step 4: Run focused API tests and verify GREEN**

Run: python -m pytest apps/api/tests/test_assignments.py apps/api/tests/test_class_access.py -q

Expected: PASS; only an assigned teacher can publish tenant-local work and published item selection cannot change.

- [ ] **Step 5: Commit teacher lifecycle**

~~~powershell
python -m ruff format apps/api
python -m ruff check apps/api
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_assignments.py
git commit -m "feat(api): publish class assignments"
~~~

### Task 3: Expose student assignments and protect answer submission

**Files:**
- Modify: apps/api/src/edu_grader_api/services/assignments.py
- Modify: apps/api/src/edu_grader_api/routers/assignments.py
- Modify: apps/api/tests/test_assignments.py

**Interfaces:**
- Consumes: published Assignment, AssignmentItem, Enrollment, and Task 2 services.
- Produces: list_student_assignments, get_student_assignment, save_answer, and submit_attempt.

- [ ] **Step 1: Add failing student, conflict, and idempotency tests**

~~~python
def test_enrolled_student_lists_pending_and_opens_frozen_assignment(client, session) -> None:
    listed = client.get("/v1/student/assignments", headers=authorize(client, student))
    assert [entry["id"] for entry in listed.json()["pending"]] == [str(assignment.id)]
    detail = client.get(f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student))
    assert detail.status_code == 200
    assert detail.json()["items"][0]["question_version_id"] == str(published_version.id)

def test_answer_save_rejects_stale_version_and_submitted_attempt(client, session) -> None:
    saved = client.put(answer_url, headers=authorize(client, student),
                       json={"answer": {"value": "5"}, "version": 0})
    assert saved.json()["version"] == 1
    conflict = client.put(answer_url, headers=authorize(client, student),
                          json={"answer": {"value": "6"}, "version": 0})
    assert conflict.status_code == 409
    assert conflict.json()["current"]["answer"] == {"value": "5"}

def test_submit_replays_a_matching_idempotency_key(client, session) -> None:
    headers = authorize(client, student) | {"Idempotency-Key": str(uuid4())}
    first = client.post(submit_url, headers=headers)
    retry = client.post(submit_url, headers=headers)
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert session.scalar(select(func.count(SubmissionReceipt.id))) == 1
~~~

- [ ] **Step 2: Run the tests and verify RED**

Run: python -m pytest apps/api/tests/test_assignments.py -q

Expected: FAIL because student routes, version handling, and receipt replay are absent.

- [ ] **Step 3: Implement student API and transaction semantics**

Expose:
- GET /v1/student/assignments
- GET /v1/student/assignments/{assignment_id}
- PUT /v1/student/attempts/{attempt_id}/answers/{assignment_item_id}
- POST /v1/student/assignments/{assignment_id}/submit

Detail creates or retrieves exactly attempt_number 1 for an enrolled student and returns only published assignment metadata, frozen items, existing answers, versions, and progress. List groups results as pending, correction_required, completed; correction_required is empty until Issue #7.

save_answer accepts version 0 only for a missing row. For an existing row, issue an UPDATE constrained by AttemptAnswer.version == expected_version and increment atomically. A stale write returns HTTP 409 body {"current": {"answer": current.answer_json, "version": current.version}}. Reject non-owner, non-enrollment, and non-draft paths without revealing records.

submit validates one UUID Idempotency-Key. Inside one transaction: read an existing receipt before state mutation, reject a key belonging to another assignment or differing fingerprint, verify attempt status is draft, mark it submitted, create exactly one receipt with response {"attempt_id": str(attempt.id), "status": "submitted"}, and append student_attempt.submitted audit data without answer_json. Missing/malformed key is 400; a non-draft server-side attempt is 409; cross-tenant/non-enrolled is 404. Local outbox/conflict gating is enforced by Task 4 because the server cannot observe browser-local mutations.

- [ ] **Step 4: Run complete API coverage and verify GREEN**

Run:
~~~powershell
python -m pytest apps/api/tests/test_assignments.py -q
python -m pytest apps/api/tests -q
~~~

Expected: PASS; conflicts preserve the server value, retries create one receipt, and unauthorized callers cannot enumerate assignments or attempts.

- [ ] **Step 5: Commit student API**

~~~powershell
python -m ruff format apps/api
python -m ruff check apps/api
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/tests/test_assignments.py
git commit -m "feat(api): save and submit student attempts"
~~~

### Task 4: Build local drafts and ordered synchronization test-first

**Files:**
- Modify: apps/web/package.json
- Create: apps/web/vitest.config.ts
- Create: apps/web/app/lib/drafts.ts
- Create: apps/web/app/composables/useAssignmentSync.ts
- Create: apps/web/tests/drafts.test.ts
- Create: apps/web/tests/assignment-sync.test.ts

**Interfaces:**
- Consumes: Task 3 list/detail/save/submit JSON contracts.
- Produces: queueAnswer, flushAttempt, submitAttempt, and SyncStatus for Task 5.

- [ ] **Step 1: Add test tooling and write failing local-first tests**

Install dexie, vitest, and fake-indexeddb; add npm script "test": "vitest run"; configure fake-indexeddb/auto in test setup.

~~~ts
it('persists an answer and coalesces later edits into one queued mutation', async () => {
  await queueAnswer({ tenantId: 't-1', userId: 'u-1', attemptId: 'a-1', itemId: 'i-1',
                      answer: { value: '5' }, version: 0 })
  await queueAnswer({ tenantId: 't-1', userId: 'u-1', attemptId: 'a-1', itemId: 'i-1',
                      answer: { value: '6' }, version: 0 })
  expect(await drafts.get(['u-1', 'a-1', 'i-1'])).toMatchObject({ answer: { value: '6' }, status: 'saved_locally' })
  expect(await outbox.where({ attemptId: 'a-1', itemId: 'i-1' }).count()).toBe(1)
})
~~~

~~~ts
it('retains offline work and marks conflicts without overwriting local data', async () => {
  const api = { saveAnswer: vi.fn().mockResolvedValueOnce({ kind: 'offline' })
                   .mockResolvedValueOnce({ kind: 'conflict', current: { answer: { value: '4' }, version: 2 } }) }
  await flushAttempt('a-1', api)
  expect(await draftStatus('a-1', 'i-1')).toBe('offline')
  await flushAttempt('a-1', api)
  expect(await draftStatus('a-1', 'i-1')).toBe('conflict')
})
~~~

- [ ] **Step 2: Run and verify RED**

Run: npm test -- tests/drafts.test.ts tests/assignment-sync.test.ts

Expected: FAIL because the test script and modules do not exist.

- [ ] **Step 3: Implement Dexie store and synchronizer**

HomeworkDraftDatabase has drafts and outbox tables keyed by tenantId, userId, attemptId, itemId. queueAnswer replaces the attempt/item outbox record and writes the local draft in one Dexie transaction. flushAttempt processes records by updatedAt; it removes only acknowledged writes, stores the returned server version, leaves network failures queued as offline, and stops retries after a 409 while retaining local and server answers. submitAttempt rejects while any outbox row or conflict exists and retains a UUID key until its response is accepted.

- [ ] **Step 4: Run web data-layer tests and verify GREEN**

Run: npm test -- tests/drafts.test.ts tests/assignment-sync.test.ts

Expected: PASS; data survives reopening the database, offline data queues, conflicts stay visible, and submit retries preserve their key.

- [ ] **Step 5: Commit local-first client data layer**

~~~powershell
git add apps/web/package.json apps/web/vitest.config.ts apps/web/app/lib/drafts.ts apps/web/app/composables/useAssignmentSync.ts apps/web/tests
git commit -m "feat(web): persist and sync assignment drafts"
~~~

### Task 5: Replace student scaffold with list and answering pages

**Files:**
- Modify: apps/web/app/pages/student/index.vue
- Create: apps/web/app/pages/student/assignments/[assignmentId].vue
- Modify: apps/web/app/assets/css/main.css
- Modify: apps/web/tests/assignment-sync.test.ts

**Interfaces:**
- Consumes: Task 4 synchronizer and Task 3 APIs.
- Produces: visible list grouping, navigation, sync statuses, unanswered warning, and safe submission interaction.

- [ ] **Step 1: Write a failing page-flow test**

~~~ts
it('disables submission offline and preserves an unanswered warning after reconnect', async () => {
  renderAssignmentPage({ online: false, items: [{ id: 'i-1' }, { id: 'i-2' }],
                         answers: [{ itemId: 'i-1', answer: { value: '5' } }] })
  expect(screen.getByRole('button', { name: '提交作业' })).toBeDisabled()
  await setOnline(true)
  await user.click(screen.getByRole('button', { name: '提交作业' }))
  expect(screen.getByText('还有 1 题未作答')).toBeVisible()
})
~~~

- [ ] **Step 2: Run and verify RED**

Run: npm test -- tests/assignment-sync.test.ts

Expected: FAIL because no assignment page or submit integration exists.

- [ ] **Step 3: Implement responsive student pages**

Replace hard-coded cards with API data and explicit pending/correction_required/completed sections. Add the assignment page with subject, due time, question count, progress, numbered navigation, previous/next controls, textarea fallback answer editor, per-item synchronization copy, and submission button. queueAnswer must occur before flushAttempt. Register online, pagehide, and visibilitychange listeners only on the client to request flushes; do not report success until the API response is received. Add status colors plus text/icon distinctions.

- [ ] **Step 4: Run web test and production build**

Run:
~~~powershell
npm test
npm run build
~~~

Expected: PASS; offline submission is unavailable, unanswered work is disclosed, and repeated submit uses the stored key.

- [ ] **Step 5: Commit student user experience**

~~~powershell
git add apps/web/app/pages/student apps/web/app/assets/css/main.css apps/web/tests
git commit -m "feat(web): add student assignment workflow"
~~~

### Task 6: Verify migrations and document operations

**Files:**
- Modify: README.md
- Modify: Makefile
- Modify: docs/superpowers/specs/2026-07-18-student-submissions-design.md
- Create or Modify: apps/api/tests/test_migrations.py

**Interfaces:**
- Consumes: Tasks 1 through 5.
- Produces: documented local migration, test, and verification commands.

- [ ] **Step 1: Write a failing migration smoke assertion**

~~~python
def test_assignment_migration_creates_submission_receipts(postgres_database_url: str) -> None:
    result = run_alembic_upgrade(postgres_database_url)
    assert result.returncode == 0, result.stderr
    assert table_exists(postgres_database_url, "submission_receipts")
~~~

- [ ] **Step 2: Verify migration RED/GREEN**

Run: python -m alembic -c apps/api/alembic.ini upgrade head

Expected: before Task 1, head lacks 0003; after Task 1, 0003 applies and the receipts table exists. Repair migration failures before continuing.

- [ ] **Step 3: Document the workflow**

Document assignment creation → publication → browser-local draft → synchronization → online submission. State that conflict resolution is explicit, submitted attempts are immutable, and request bodies/tokens must not be logged. Add Make targets api-test, web-test, and web-build that call the existing Python/npm commands.

- [ ] **Step 4: Run the complete quality gate**

Run:
~~~powershell
python -m pytest apps/api/tests services/grader/tests -q
python -m ruff check apps/api services/grader
python -m ruff format --check apps/api services/grader
npm --prefix apps/web test
npm --prefix apps/web run build
docker compose config
git diff --check
~~~

Expected: every command exits 0.

- [ ] **Step 5: Commit documentation and verification updates**

~~~powershell
git add README.md Makefile docs/superpowers/specs/2026-07-18-student-submissions-design.md apps/api/tests/test_migrations.py
git commit -m "docs: document student submission operations"
~~~

## Plan Self-Review

- Spec coverage: Tasks 1–3 cover tenant scope, frozen question versions, list groups, optimistic locking, receipt-backed idempotency, immutable submission, and audits. Tasks 4–5 cover IndexedDB, queueing, offline/reconnect states, lifecycle-triggered sync attempts, navigation, and warnings. Task 6 covers operation and verification.
- Placeholder scan: every task names exact files, interfaces, test code, commands, expected outcomes, and commits.
- Type consistency: Assignment, AssignmentItem, StudentAttempt, AttemptAnswer, SubmissionReceipt, queueAnswer, flushAttempt, and submitAttempt are introduced before consumers reference them.
