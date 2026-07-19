# Guardian Consent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce school-verified guardian consent and withdrawal for students flagged as under fourteen without collecting guardian contact data.

**Architecture:** A single per-student consent record stores a minimum status, opaque evidence reference, notice version, verifier and optimistic version. Roster import atomically updates it, while a FastAPI dependency gates student processing before assignments, submissions, appeals and outbound grading can execute. Status changes use the existing signed audit ledger.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, SQLAlchemy 2, Alembic, PostgreSQL, pytest.

## Global Constraints

- Do not store a birth date, guardian name, email, phone, identity document, consent form body or scanned signature.
- `student_under_14` is the only age fact. It requires a `pending` or `granted` consent state.
- An under-fourteen student may process new data only with `granted`; `withdrawn` and `pending` return 403 `guardian consent required`.
- Existing records remain read-only after withdrawal; deletion and export are separate future workflows.
- Audit metadata contains status, notice version, opaque evidence reference and record version only.

---

### Task 1: Consent model and migration

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0008_guardian_consents.py`
- Create: `apps/api/tests/test_guardian_consent_models.py`

**Interfaces:**
- Produces `GuardianConsentStatus` with `NOT_REQUIRED`, `PENDING`, `GRANTED`, `WITHDRAWN`.
- Produces `StudentGuardianConsent(student_id, requires_guardian_consent, status, notice_version, evidence_reference, verified_by_user_id, granted_at, withdrawn_at, withdrawal_reason, version)`.

- [ ] **Step 1: Write failing model tests**

    def test_guardian_consent_is_unique_per_student() -> None:
        first = StudentGuardianConsent(
            student_id=student.id, requires_guardian_consent=True,
            status=GuardianConsentStatus.PENDING,
        )
        second = StudentGuardianConsent(
            student_id=student.id, requires_guardian_consent=True,
            status=GuardianConsentStatus.PENDING,
        )
        session.add_all([first, second])
        with pytest.raises(IntegrityError):
            session.commit()

    def test_not_required_consent_needs_no_evidence() -> None:
        consent = StudentGuardianConsent(
            student_id=student.id, requires_guardian_consent=False,
            status=GuardianConsentStatus.NOT_REQUIRED,
        )
        session.add(consent)
        session.commit()

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest apps/api/tests/test_guardian_consent_models.py -q`

Expected: FAIL because the model and enum do not exist.

- [ ] **Step 3: Implement minimal model and migration**

Use `student_id` as the primary key and foreign key to `users.id`. Enforce `requires_guardian_consent = false` only with `not_required`, and require `notice_version`, `evidence_reference`, `verified_by_user_id`, and `granted_at` for `granted`. Store references in `String(100)` and reject control characters in the service layer. Add an Alembic migration with the enum represented as a portable string column, a check constraint for the `not_required` combination, and indexes for status lookup.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_guardian_consent_models.py apps/api/tests/test_models.py -q`

Expected: PASS.

    git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0008_guardian_consents.py apps/api/tests/test_guardian_consent_models.py
    git commit -m "feat: add guardian consent records"

### Task 2: Atomic roster consent import

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/roster.py`
- Modify: `apps/api/tests/test_roster_import.py`
- Modify: `docs/data-inventory.md`

**Interfaces:**
- `RosterRow` gains `student_under_14: bool`, `guardian_consent_status: GuardianConsentStatus`, `guardian_consent_notice_version: str | None`, and `guardian_consent_evidence_reference: str | None`.
- `import_roster(session, actor, rows)` creates or updates the matching `StudentGuardianConsent` in its current transaction.

- [ ] **Step 1: Write failing import tests**

    def test_import_persists_a_granted_guardian_consent(admin_client, session) -> None:
        response = admin_client.post(
            "/v1/admin/students/import",
            files={"file": ("roster.csv", (
                "class_code,class_name,student_school_id,student_display_name,"
                "student_under_14,guardian_consent_status,"
                "guardian_consent_notice_version,guardian_consent_evidence_reference\n"
                "7A,Year 7 A,S-001,Student,true,granted,v1,CONSENT-001\n"
            ), "text/csv")},
        )
        assert response.status_code == 200
        consent = session.scalar(select(StudentGuardianConsent))
        assert consent.status is GuardianConsentStatus.GRANTED
        assert consent.evidence_reference == "CONSENT-001"

    def test_import_rolls_back_invalid_under_fourteen_consent(admin_client, session) -> None:
        response = admin_client.post(... "true,not_required,,\n" ...)
        assert response.status_code == 422
        assert session.scalar(select(User)) is None

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest apps/api/tests/test_roster_import.py -q`

Expected: FAIL because the new CSV columns are rejected.

- [ ] **Step 3: Implement strict parser and audit**

Replace `EXPECTED_HEADERS` with the eight exact columns above. Parse booleans only from lowercase `true` and `false`; validate status combinations before any database write. Reject evidence references with whitespace-only content, control characters, `@`, more than 100 characters, or 11-or-more consecutive digits. Upsert the consent row with the roster in the transaction and append `guardian_consent.imported` with `{status, notice_version, evidence_reference, version}` only.

Update `docs/data-inventory.md` to list this table under Identity/roster as restricted, school-admin access, and the same active-enrollment-plus-two-years retention rule.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_roster_import.py apps/api/tests/test_audit.py -q`

Expected: PASS.

    git add apps/api/src/edu_grader_api/services/roster.py apps/api/tests/test_roster_import.py docs/data-inventory.md
    git commit -m "feat: import guardian consent status"

### Task 3: Student processing gate and consent administration

**Files:**
- Create: `apps/api/src/edu_grader_api/services/guardian_consents.py`
- Create: `apps/api/src/edu_grader_api/routers/guardian_consents.py`
- Modify: `apps/api/src/edu_grader_api/dependencies.py`, `main.py`
- Modify: `routers/assignments.py`, `routers/appeals.py`
- Create: `apps/api/tests/test_guardian_consents.py`

**Interfaces:**
- Produces `require_student_consent(principal: CurrentPrincipal, session: Session) -> CurrentPrincipal`.
- Produces `grant_guardian_consent(session, *, tenant_id, admin_id, student_id, expected_version, notice_version, evidence_reference) -> StudentGuardianConsent`.
- Produces `withdraw_guardian_consent(session, *, tenant_id, admin_id, student_id, expected_version, reason) -> StudentGuardianConsent`.

- [ ] **Step 1: Write failing gate and administration tests**

    def test_pending_student_cannot_read_or_submit_assignment(api_client, session) -> None:
        student, assignment = pending_student_assignment(session)
        assert api_client.get(
            f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
        ).status_code == 403
        assert api_client.post(
            f"/v1/student/assignments/{assignment.id}/submit",
            headers={**authorize(api_client, student), "Idempotency-Key": str(uuid4())},
        ).status_code == 403

    def test_admin_withdrawal_blocks_new_appeal_and_audits(api_client, session) -> None:
        response = api_client.post(
            f"/v1/admin/students/{student.id}/guardian-consent/withdraw",
            headers=authorize(api_client, admin),
            json={"version": 0, "reason": "guardian request"},
        )
        assert response.status_code == 200
        assert consent.status is GuardianConsentStatus.WITHDRAWN
        assert audit_event(session, "guardian_consent.withdrawn")

- [ ] **Step 2: Confirm failure**

Run: `python -m pytest apps/api/tests/test_guardian_consents.py apps/api/tests/test_assignments.py apps/api/tests/test_appeals.py -q`

Expected: FAIL because no consent gate or admin endpoints exist.

- [ ] **Step 3: Implement gate and routes**

The dependency must query the student's consent by internal UUID. Missing consent is allowed only while a legacy student has no `student_under_14` record; all imported rows have a consent record. For `pending` or `withdrawn`, raise `HTTPException(403, "guardian consent required")` before service calls. Apply it to every student assignment read/save/submit route and student appeal create/list routes.

Add admin routes:

    POST /v1/admin/students/{student_id}/guardian-consent/grant
    POST /v1/admin/students/{student_id}/guardian-consent/withdraw

Grant requires `{version, notice_version, evidence_reference}` and moves `pending` or `withdrawn` to `granted`. Withdraw requires `{version, reason}` and moves only `granted` to `withdrawn`. Both increment `version`, use the current transaction, and append `guardian_consent.granted` or `guardian_consent.withdrawn`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_guardian_consents.py apps/api/tests/test_assignments.py apps/api/tests/test_appeals.py apps/api/tests/test_audit.py -q`

Expected: PASS.

    git add apps/api/src/edu_grader_api/services/guardian_consents.py apps/api/src/edu_grader_api/routers/guardian_consents.py apps/api/src/edu_grader_api/dependencies.py apps/api/src/edu_grader_api/main.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/src/edu_grader_api/routers/appeals.py apps/api/tests/test_guardian_consents.py
    git commit -m "feat: gate student processing on guardian consent"

### Task 4: Full verification and operational handoff

**Files:**
- Modify: `SECURITY.md`
- Test: all API tests and PostgreSQL migration.

- [ ] **Step 1: Add release instructions**

Add the required school workflow to `SECURITY.md`: verify guardian authority and retain original evidence outside the platform; generate a non-personal evidence reference; import the status; record withdrawals promptly; retain existing records only for required storage and security purposes.

- [ ] **Step 2: Run full verification**

    python -m pytest apps/api/tests packages/processor-policy/tests services/grader/tests
    python -m ruff check apps/api services/grader packages/processor-policy
    python -m alembic -c apps/api/alembic.ini upgrade head

Expected: tests and lint pass; migration reaches `0008_guardian_consents`.

- [ ] **Step 3: Commit documentation**

    git add SECURITY.md
    git commit -m "docs: record guardian consent operations"

If documentation is unchanged after review, do not make an empty commit.
