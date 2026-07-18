# Student Appeals and Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students appeal published grades and complete teacher-approved correction attempts without mutating original work.

**Architecture:** Add immutable appeal decisions and a correction-attempt link to the existing attempt model. Reuse submission, review-task, and publication services for correction attempts; student responses expose only their own appeal state and published correction summaries.

**Tech Stack:** Python, FastAPI, Pydantic, SQLAlchemy, Alembic, pytest.

## Global Constraints

- Appeals require a published original attempt and a non-empty student reason.
- Approval/rejection is class-teacher scoped, versioned, audited, and rejection requires a reason.
- Correction answers, grading runs, review tasks, and publications are separate from originals.
- Students never receive unpublished scores, rules, signals, or teacher evidence.

---

### Task 1: Persist appeals and correction links

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py`
- Create: `apps/api/alembic/versions/0006_student_appeals_and_corrections.py`
- Create: `apps/api/tests/test_appeal_models.py`

**Interfaces:** Produces `AppealStatus`, `ReviewAppeal`, and `CorrectionAttempt`.

- [ ] **Step 1: Write failing model tests**

```python
def test_appeal_and_correction_tables_are_registered() -> None:
    assert "review_appeals" in Base.metadata.tables
    assert "correction_attempts" in Base.metadata.tables
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest apps/api/tests/test_appeal_models.py -q`

Expected: import or metadata assertion failure.

- [ ] **Step 3: Add ORM and migration**

```python
class AppealStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"

class ReviewAppeal(Base):
    __tablename__ = "review_appeals"
    # original_attempt_id, student_id, reason, status, version, decision_reason,
    # decided_by_user_id, created_at, decided_at

class CorrectionAttempt(Base):
    __tablename__ = "correction_attempts"
    # original_attempt_id, correction_attempt_id, appeal_id, created_at
```

Use an `active_key` pattern to enforce one open appeal per original attempt. The migration depends on `0005_teacher_review_and_publication`.

- [ ] **Step 4: Verify green and commit**

Run: `python -m pytest apps/api/tests/test_appeal_models.py -q`

Expected: PASS.

```bash
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0006_student_appeals_and_corrections.py apps/api/tests/test_appeal_models.py
git commit -m "feat(api): add appeal and correction domain"
```

### Task 2: Create and decide student appeals

**Files:**
- Create: `apps/api/src/edu_grader_api/services/appeals.py`
- Create: `apps/api/src/edu_grader_api/routers/appeals.py`
- Modify: `apps/api/src/edu_grader_api/main.py`
- Create: `apps/api/tests/test_appeals.py`

**Interfaces:** Produces `create_student_appeal`, `list_student_appeals`, and `decide_appeal`.

- [ ] **Step 1: Write failing API tests**

```python
def test_student_can_appeal_only_a_published_attempt(client, session):
    response = client.post(f"/v1/student/attempts/{attempt.id}/appeals", json={"reason": "Please review."}, headers=student_headers)
    assert response.status_code == 201
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest apps/api/tests/test_appeals.py -q`

Expected: `404` because appeal routes do not exist.

- [ ] **Step 3: Implement state transitions**

```python
def decide_appeal(session: Session, *, appeal_id: UUID, teacher_id: UUID, version: int, approve: bool, reason: str | None) -> ReviewAppeal:
    appeal = get_teacher_appeal(session, appeal_id=appeal_id, teacher_id=teacher_id)
    if appeal.status is not AppealStatus.OPEN or appeal.version != version:
        raise AppealConflictError()
    if not approve and not (reason and reason.strip()):
        raise AppealValidationError("reason is required")
    # approval creates a fresh StudentAttempt and CorrectionAttempt link; rejection records the reason.
```

Write `student_appeal.created` and `student_appeal.decided` audit events. Map inaccessible resources to `404`, stale/duplicate actions to `409`, and invalid payloads to `422`.

- [ ] **Step 4: Verify and commit**

Run: `python -m pytest apps/api/tests/test_appeals.py -q`

Expected: PASS for published-only creation, ownership, teacher authorization, reason validation, duplicate open appeals, and stale decisions.

```bash
git add apps/api/src/edu_grader_api/services/appeals.py apps/api/src/edu_grader_api/routers/appeals.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_appeals.py
git commit -m "feat(api): add student appeal workflow"
```

### Task 3: Submit and publish independent correction attempts

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/assignments.py`
- Modify: `apps/api/src/edu_grader_api/routers/assignments.py`
- Modify: `apps/api/src/edu_grader_api/services/reviews.py`
- Modify: `apps/api/tests/test_grade_publication.py`

- [ ] **Step 1: Write failing correction-isolation test**

```python
def test_correction_submission_preserves_original_answer_and_publication(client, session):
    correction = approve_appeal(session)
    save_answer(session, attempt_id=correction.id, answer_json={"value": "corrected"}, expected_version=0)
    assert original_answer.answer_json == {"value": "original"}
```

- [ ] **Step 2: Verify red**

Run: `python -m pytest apps/api/tests/test_grade_publication.py -q`

Expected: correction attempt cannot yet be opened or saved.

- [ ] **Step 3: Reuse submission and review paths**

```python
def get_correction_attempt(session: Session, *, tenant_id: UUID, student_id: UUID, correction_id: UUID) -> StudentAttempt:
    # Require the correction link, original assignment enrollment, and student ownership.
```

Allow answer save/submit only for the approved correction attempt. Existing grading creates its own `GradingRun` and `ReviewTask`; existing teacher publication creates a separate `GradePublication`.

- [ ] **Step 4: Verify privacy and commit**

Run: `python -m pytest apps/api/tests/test_appeals.py apps/api/tests/test_grade_publication.py -q`

Expected: correction scores absent before publication, present only after correction publication, and original answers unchanged.

```bash
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/src/edu_grader_api/services/reviews.py apps/api/tests/test_grade_publication.py
git commit -m "feat(api): submit and publish corrections"
```

### Task 4: Full verification

- [ ] Run `python -m ruff format --check apps/api`, `python -m ruff check apps/api`, `python -m pytest apps/api/tests -q`, `docker compose config`, and `git diff --check`.
- [ ] Record that analytics remains the final Issue #7 slice; do not alter immutable original attempt data.
