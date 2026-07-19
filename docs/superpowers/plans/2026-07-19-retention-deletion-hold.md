# Retention and Deletion Hold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an administrator-operated, auditable erasure workflow that immediately restricts new student processing, honors legal holds, and safely removes student operational data while preserving the immutable audit linkage through a de-identified user shell.

**Architecture:** Store one active `PrivacyRequest` per student and use it as the shared processing restriction signal. The admin router delegates transitions to a service that validates tenant scope, state and optimistic version before appending an audit entry. A separate explicit command performs dry-run or executed cleanup, rechecks the request in its own transaction, deletes the dependency graph in foreign-key-safe order, and de-identifies rather than deletes `users` so append-only audit records remain valid.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL, pytest, argparse.

## Global Constraints

- A school administrator records a request only after verifying it outside the platform; no requester identity, contact data, evidence files or form contents are stored.
- `requested`, `legal_hold`, and `approved` requests block student assignment reads, saves, submissions and appeals with `403 data processing restricted` before service calls.
- Only `admin` can create or transition a request; all operations are tenant-scoped and use optimistic version checks.
- A legal hold prevents approval and cleanup; cleanup is dry-run by default and requires `--execute`.
- Cleanup deletes student operational data and de-identifies the `users` row, but does not delete or mutate `audit_logs`, assignments, questions, policies, tenants or audit chain heads.
- Audit metadata contains only request type, status, version and deadline; it contains no reason, answer content, school ID, name or OIDC subject.

---

### Task 1: Privacy request persistence and migration

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0009_privacy_requests.py`
- Create: `apps/api/tests/test_privacy_request_models.py`

**Interfaces:**
- Produces `PrivacyRequestType.ERASURE` and `PrivacyRequestStatus.REQUESTED`, `LEGAL_HOLD`, `APPROVED`, `REJECTED`, `COMPLETED`.
- Produces `PrivacyRequest(id, tenant_id, student_id, request_type, status, reason, hold_reason, requested_by_user_id, decided_by_user_id, requested_at, decided_at, eligible_for_deletion_at, completed_at, version)`.
- Produces a partial unique index named `uq_privacy_requests_active_student` for statuses `requested`, `legal_hold`, and `approved`.

- [ ] **Step 1: Write failing model tests**

```python
def test_only_one_active_erasure_request_exists_for_a_student() -> None:
    session.add_all(
        [
            PrivacyRequest(student_id=student.id, tenant_id=tenant.id,
                           request_type=PrivacyRequestType.ERASURE,
                           status=PrivacyRequestStatus.REQUESTED, reason="school request",
                           requested_by_user_id=admin.id),
            PrivacyRequest(student_id=student.id, tenant_id=tenant.id,
                           request_type=PrivacyRequestType.ERASURE,
                           status=PrivacyRequestStatus.APPROVED, reason="school request",
                           requested_by_user_id=admin.id),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_rejected_request_does_not_block_a_later_active_request() -> None:
    rejected = PrivacyRequest(
        student_id=student.id, tenant_id=tenant.id,
        request_type=PrivacyRequestType.ERASURE,
        status=PrivacyRequestStatus.REJECTED, reason="school request",
        requested_by_user_id=admin.id,
    )
    requested = PrivacyRequest(
        student_id=student.id, tenant_id=tenant.id,
        request_type=PrivacyRequestType.ERASURE,
        status=PrivacyRequestStatus.REQUESTED, reason="new school request",
        requested_by_user_id=admin.id,
    )
    session.add_all([rejected, requested])
    session.commit()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_privacy_request_models.py -q`

Expected: collection fails because `PrivacyRequest` and its enums do not exist.

- [ ] **Step 3: Add the model and portable partial-index migration**

```python
class PrivacyRequestStatus(StrEnum):
    REQUESTED = "requested"
    LEGAL_HOLD = "legal_hold"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


ACTIVE_PRIVACY_REQUEST_STATUSES = (
    PrivacyRequestStatus.REQUESTED.value,
    PrivacyRequestStatus.LEGAL_HOLD.value,
    PrivacyRequestStatus.APPROVED.value,
)


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        Index(
            "uq_privacy_requests_active_student",
            "student_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'legal_hold', 'approved')"),
            sqlite_where=text("status IN ('requested', 'legal_hold', 'approved')"),
        ),
    )
```

Make `reason` and `hold_reason` `String(500)`, use portable `String` columns in the migration, and create the same filtered index with `postgresql_where` and `sqlite_where`. Foreign-key `student_id`, actor IDs and `tenant_id` to existing `users`/`tenants` tables. Do not cascade any foreign key.

- [ ] **Step 4: Verify the model and existing model suite**

Run: `python -m pytest apps/api/tests/test_privacy_request_models.py apps/api/tests/test_models.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the persistence slice**

```bash
git add apps/api/src/edu_grader_api/models.py \
  apps/api/alembic/versions/0009_privacy_requests.py \
  apps/api/tests/test_privacy_request_models.py
git commit -m "feat: add privacy request records"
```

### Task 2: Admin request lifecycle and processing restriction

**Files:**
- Create: `apps/api/src/edu_grader_api/services/privacy_requests.py`
- Create: `apps/api/src/edu_grader_api/routers/privacy_requests.py`
- Modify: `apps/api/src/edu_grader_api/dependencies.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Modify: `apps/api/src/edu_grader_api/routers/assignments.py`
- Modify: `apps/api/src/edu_grader_api/routers/appeals.py`
- Create: `apps/api/tests/test_privacy_requests.py`

**Interfaces:**
- Produces `create_privacy_request`, `hold_privacy_request`, `approve_privacy_request`, and `reject_privacy_request` service functions.
- Produces `require_student_processing_allowed(principal, session) -> CurrentPrincipal`.
- Serves `POST /v1/admin/students/{student_id}/privacy-requests`, `POST /v1/admin/privacy-requests/{request_id}/hold`, `POST /v1/admin/privacy-requests/{request_id}/approve`, and `POST /v1/admin/privacy-requests/{request_id}/reject`.

- [ ] **Step 1: Write failing lifecycle and gate tests**

```python
def test_request_immediately_blocks_every_student_processing_route(client, session) -> None:
    admin, student = student_and_admin(session)
    created = client.post(
        f"/v1/admin/students/{student.id}/privacy-requests",
        headers=authorize(client, admin),
        json={"reason": "school verified request"},
    )
    assert created.status_code == 201
    for method, path, payload in student_processing_requests(student):
        response = getattr(client, method)(path, headers=authorize(client, student), **payload)
        assert response.status_code == 403
        assert response.json() == {"detail": "data processing restricted"}


def test_hold_blocks_approval_and_rejection_releases_processing(client, session) -> None:
    admin, student, request = create_requested_request(session)
    headers = authorize(client, admin)
    held = client.post(
        f"/v1/admin/privacy-requests/{request.id}/hold",
        headers=headers, json={"reason": "incident", "version": 0},
    )
    assert held.status_code == 200
    approval = client.post(
        f"/v1/admin/privacy-requests/{request.id}/approve",
        headers=headers,
        json={"version": 1, "eligible_for_deletion_at": "2026-07-20T00:00:00+00:00"},
    )
    assert approval.status_code == 422
    rejected = client.post(
        f"/v1/admin/privacy-requests/{request.id}/reject",
        headers=headers, json={"reason": "request withdrawn", "version": 1},
    )
    assert rejected.status_code == 200
    assert client.get("/v1/student/assignments", headers=authorize(client, student)).status_code == 200
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_privacy_requests.py -q`

Expected: route is not found and the processing dependency is absent.

- [ ] **Step 3: Implement services, routes, events and shared gate**

```python
def require_student_processing_allowed(
    principal: Annotated[CurrentPrincipal, Depends(require_student_consent)],
    session: Annotated[Session, Depends(get_session)],
) -> CurrentPrincipal:
    active = session.scalar(
        select(PrivacyRequest.id).where(
            PrivacyRequest.student_id == UUID(principal.user_id),
            PrivacyRequest.status.in_(ACTIVE_PRIVACY_REQUEST_STATUSES),
        )
    )
    if active is not None:
        raise HTTPException(403, "data processing restricted")
    return principal
```

Require a nonblank reason on create, hold and reject. Require an ISO-8601 `eligible_for_deletion_at` on approval and reject values earlier than the request time. Every transition must load by request UUID plus tenant UUID, compare `version`, validate the exact predecessor status, increment the version and append the corresponding `privacy_request.*` audit entry in the same transaction. Map missing/other-tenant rows to `404`, duplicate active request or stale version to `409`, and invalid transitions to `422`.

Replace every student `Depends(require_student_consent)` in assignment and appeal routers with `Depends(require_student_processing_allowed)`. Preserve the guardian-consent check by nesting it in the new dependency.

- [ ] **Step 4: Verify the lifecycle and regression suites**

Run: `python -m pytest apps/api/tests/test_privacy_requests.py apps/api/tests/test_guardian_consents.py apps/api/tests/test_assignments.py apps/api/tests/test_appeals.py apps/api/tests/test_audit.py -q`

Expected: all tests pass, including existing guardian-consent behavior.

- [ ] **Step 5: Commit the lifecycle slice**

```bash
git add apps/api/src/edu_grader_api/services/privacy_requests.py \
  apps/api/src/edu_grader_api/routers/privacy_requests.py \
  apps/api/src/edu_grader_api/dependencies.py \
  apps/api/src/edu_grader_api/main.py \
  apps/api/src/edu_grader_api/routers/assignments.py \
  apps/api/src/edu_grader_api/routers/appeals.py \
  apps/api/tests/test_privacy_requests.py
git commit -m "feat: restrict processing for privacy requests"
```

### Task 3: Dry-run and executed privacy cleanup command

**Files:**
- Create: `apps/api/src/edu_grader_api/services/privacy_cleanup.py`
- Create: `apps/api/src/edu_grader_api/privacy_cleanup.py`
- Create: `apps/api/tests/test_privacy_cleanup.py`

**Interfaces:**
- Produces `eligible_privacy_requests(session, now) -> list[PrivacyRequest]`.
- Produces `complete_privacy_request(session, *, request_id, actor_user_id, now) -> CleanupResult`.
- Serves `python -m edu_grader_api.privacy_cleanup [--execute] [--request-id UUID]`.

- [ ] **Step 1: Write failing cleanup tests**

```python
def test_cleanup_dry_run_leaves_every_record_unchanged(session) -> None:
    request, student, _, _, _ = approved_request_with_attempt_graph(
        session, eligible_at=past_time
    )
    candidates = eligible_privacy_requests(session, now=utc_now())
    assert [candidate.id for candidate in candidates] == [request.id]
    assert session.get(User, student.id).school_id == "S-001"


def test_execute_cleanup_deletes_operational_graph_and_deidentifies_user(session) -> None:
    request, student, attempt, admin, tenant = approved_request_with_attempt_graph(
        session, eligible_at=past_time
    )
    result = complete_privacy_request(
        session, request_id=request.id, actor_user_id=admin.id, now=utc_now()
    )
    assert result.status is PrivacyRequestStatus.COMPLETED
    assert session.get(StudentAttempt, attempt.id) is None
    erased = session.get(User, student.id)
    assert erased is not None
    assert erased.oidc_issuer is None and erased.oidc_subject is None
    assert erased.school_id.startswith("erased-")
    assert verify_audit_chain(session, tenant_id=tenant.id).valid is True
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_privacy_cleanup.py -q`

Expected: collection fails because the cleanup service and command do not exist.

- [ ] **Step 3: Implement dependency-safe cleanup and the explicit command**

Delete the graph using SQLAlchemy `delete()` statements in this order: `review_decisions` → `grading_signals` → `review_tasks` → `grade_publications` → `correction_attempts` → `review_appeals` → `grading_runs` → `attempt_answers` → `submission_receipts` → `student_attempts` → `enrollments` → `student_guardian_consents`. Filter every statement by the target student or the student's attempt IDs, never by an unscoped table scan.

```python
def complete_privacy_request(
    session: Session, *, request_id: UUID, actor_user_id: UUID, now: datetime
) -> CleanupResult:
    request = session.scalar(select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update())
    if request is None or request.status is not PrivacyRequestStatus.APPROVED:
        raise PrivacyCleanupSkipped("request is not approved")
    if request.eligible_for_deletion_at is None or request.eligible_for_deletion_at > now:
        raise PrivacyCleanupSkipped("request is not eligible")
    student = session.get(User, request.student_id)
    # Execute the scoped graph deletion in the documented FK order.
    student.oidc_issuer = None
    student.oidc_subject = None
    student.school_id = f"erased-{student.id}"
    student.display_name = "Erased student"
    request.status = PrivacyRequestStatus.COMPLETED
    request.completed_at = now
    request.version += 1
    append_audit_event(
        session,
        tenant_id=request.tenant_id,
        actor_user_id=actor_user_id,
        event_type="privacy_request.completed",
        target_type="privacy_request",
        target_id=request.id,
        metadata={
            "request_type": request.request_type.value,
            "status": request.status.value,
            "version": request.version,
        },
    )
```

The argparse command opens `SessionLocal.begin()`, lists eligible request IDs and deadlines when `--execute` is absent, and calls `complete_privacy_request` only when `--execute` is supplied. It must require `--request-id` for execution so an operator cannot erase several students through one broad invocation. The actor is the configured bootstrap administrator UUID supplied by `--actor-user-id`; reject execution without it.

- [ ] **Step 4: Verify dry-run, execution and audit behavior**

Run: `python -m pytest apps/api/tests/test_privacy_cleanup.py apps/api/tests/test_audit.py -q`

Expected: all tests pass; a held, future-dated or non-approved request remains unchanged.

- [ ] **Step 5: Commit the cleanup slice**

```bash
git add apps/api/src/edu_grader_api/services/privacy_cleanup.py \
  apps/api/src/edu_grader_api/privacy_cleanup.py \
  apps/api/tests/test_privacy_cleanup.py
git commit -m "feat: add controlled privacy cleanup"
```

### Task 4: Operational documentation and end-to-end verification

**Files:**
- Modify: `docs/data-inventory.md`
- Modify: `SECURITY.md`
- Test: PostgreSQL migration and complete project suite

**Interfaces:**
- Documents the `privacy_requests` retention record, legal-hold transition, processing restriction, explicit dry-run and `--execute --request-id --actor-user-id` cleanup requirements.

- [ ] **Step 1: Update the inventory and security runbook**

Add `privacy_requests` to `docs/data-inventory.md` as restricted, administrator/event-response access, retained until completed request plus the applicable policy window. State that cleanup deletes student operational content but leaves only a de-identified user shell required by immutable audit foreign keys.

Add to `SECURITY.md` the required sequence: independently verify school request; create the request; place a preservation hold if needed; approve with the policy deadline; review the dry-run; run one request at a time with explicit execute and actor UUID; retain the audit chain; never use direct SQL deletion.

- [ ] **Step 2: Run complete verification**

Run:

```bash
python -m pytest apps/api/tests packages/processor-policy/tests services/grader/tests
python -m ruff check apps/api services/grader packages/processor-policy
python -m ruff format --check apps/api services/grader packages/processor-policy
```

Create an isolated PostgreSQL container on an unused port and run:

```bash
DATABASE_URL=postgresql+psycopg://edu_grader:change-me@127.0.0.1:15433/edu_grader \
  python -m alembic -c apps/api/alembic.ini upgrade head
```

Expected: all tests and Ruff checks pass, and the database reports revision `0009_privacy_requests`.

- [ ] **Step 3: Commit documentation**

```bash
git add docs/data-inventory.md SECURITY.md
git commit -m "docs: record privacy cleanup operations"
```
