# Teacher Review and Grade Publication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an auditable teacher review queue and controlled per-attempt grade publication without exposing unpublished results to students.

**Architecture:** Keep `GradingRun` and `GradingSignal` immutable as the automatic-grading source. Add append-only `ReviewDecision` records on versioned `ReviewTask` rows, then use a per-attempt `GradePublication` record to make a bounded final score visible. Put review state transitions in a focused service module and keep HTTP schemas/routes in a dedicated router.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest, SQLite test database and PostgreSQL production database.

## Global Constraints

- Preserve every `GradingRun`, `GradingSignal`, rule snapshot, and answer snapshot after submission.
- Scope every teacher operation to the current tenant and an assigned `ClassTeacher` row; return `404` for inaccessible resources.
- A score adjustment, regrade request, and rule-problem report require a non-empty reason.
- Reject stale task versions and duplicate final handling with `409`; never overwrite a completed decision.
- Students must not receive scores, correct answers, rule snapshots, or grading evidence before a `GradePublication` exists.
- Only deterministic, non-review-required results may be batch-confirmed. Treat `E3` and `E4` as subjective in this first release.
- Use test-first development and make each task independently testable before committing.

---

## File Structure

- `apps/api/src/edu_grader_api/models.py`: review/publication enums, ORM models, relationships, and constraints.
- `apps/api/alembic/versions/0005_teacher_review_and_publication.py`: production schema for review tasks, immutable decisions, and publications.
- `apps/api/src/edu_grader_api/services/reviews.py`: authorization, queue filtering, transitions, eligibility, and published-result projection.
- `apps/api/src/edu_grader_api/services/assignments.py`: creates review tasks when an automatic grading run needs review and removes unpublished grading from submission receipts.
- `apps/api/src/edu_grader_api/routers/reviews.py`: teacher review queue, decision, batch-confirm, and publication HTTP contracts.
- `apps/api/src/edu_grader_api/routers/assignments.py`: student-safe unpublished/published assignment response projection.
- `apps/api/src/edu_grader_api/main.py`: registers the review router.
- `apps/api/tests/test_reviews.py`: unit/API coverage for review transitions, filtering, authorization, and concurrency.
- `apps/api/tests/test_grade_publication.py`: student privacy and publication eligibility coverage.

### Task 1: Persist the review and publication domain

**Files:**
- Modify: `apps/api/src/edu_grader_api/models.py:31-55,359-474`
- Create: `apps/api/alembic/versions/0005_teacher_review_and_publication.py`
- Create: `apps/api/tests/test_review_models.py`

**Interfaces:**
- Consumes: `StudentAttempt`, `AttemptAnswer`, and immutable `GradingRun` records.
- Produces: `ReviewTask`, `ReviewDecision`, `GradePublication`, `ReviewTaskStatus`, `ReviewReason`, and `ReviewAction` ORM types used by service and router tasks.

- [ ] **Step 1: Write failing model-constraint tests**

```python
def test_review_task_allows_only_one_open_task_per_answer(session: Session) -> None:
    answer, run = make_submitted_review_answer(session)
    session.add_all([
        ReviewTask(attempt_answer=answer, grading_run=run, reason=ReviewReason.NEEDS_REVIEW),
        ReviewTask(attempt_answer=answer, grading_run=run, reason=ReviewReason.NEEDS_REVIEW),
    ])
    with pytest.raises(IntegrityError):
        session.commit()


def test_review_decision_is_append_only_and_retains_score_snapshot(session: Session) -> None:
    task = make_review_task(session)
    decision = ReviewDecision(
        review_task=task,
        actor_user_id=task.attempt_answer.attempt.assignment.created_by_user_id,
        action=ReviewAction.ADJUST_SCORE,
        original_score=0,
        final_score=1,
        reason="student used an equivalent expression",
        task_version=0,
    )
    session.add(decision)
    session.commit()
    assert decision.original_score == 0
    assert decision.final_score == 1
```

- [ ] **Step 2: Run the model test to verify it fails**

Run: `python -m pytest apps/api/tests/test_review_models.py -q`

Expected: collection fails because the review ORM types do not exist.

- [ ] **Step 3: Add domain enums, models, and relationships**

```python
class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class ReviewReason(StrEnum):
    NEEDS_REVIEW = "needs_review"
    AUTO_CONFIRMATION = "auto_confirmation"
    REGRADE_REQUESTED = "regrade_requested"
    RULE_PROBLEM = "rule_problem"


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    ADJUST_SCORE = "adjust_score"
    REQUEST_REGRADE = "request_regrade"
    REPORT_RULE_PROBLEM = "report_rule_problem"


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (UniqueConstraint("attempt_answer_id", "active_key", name="uq_review_task_active_answer"),)
    active_key: Mapped[str | None] = mapped_column(String(10))


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    # id, review_task_id, actor_user_id, action, original_score, final_score,
    # reason, task_version, created_at


class GradePublication(Base):
    __tablename__ = "grade_publications"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_grade_publication_attempt"),)
    # id, attempt_id, published_by_user_id, published_at
```

Use the nullable `active_key` column for portable SQLite and PostgreSQL uniqueness: set it to `"open"` while a task is active and `None` once it is resolved or superseded. Create `ix_review_tasks_queue` on `(status, reason, created_at)` and indexes on task `grading_run_id` and publication `attempt_id`. Add relationships from `StudentAttempt`, `AttemptAnswer`, and `GradingRun`.

- [ ] **Step 4: Write migration 0005 from the ORM schema**

```python
revision = "0005_teacher_review_and_publication"
down_revision = "0004_english_grading_runs"

def upgrade() -> None:
    op.create_table("review_tasks", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("attempt_answer_id", sa.Uuid(), nullable=False), sa.Column("grading_run_id", sa.Uuid(), nullable=False), sa.Column("reason", sa.String(30), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("active_key", sa.String(10)), sa.Column("version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.ForeignKeyConstraint(["attempt_answer_id"], ["attempt_answers.id"]), sa.ForeignKeyConstraint(["grading_run_id"], ["grading_runs.id"]), sa.UniqueConstraint("attempt_answer_id", "active_key", name="uq_review_task_active_answer"))
    op.create_table("review_decisions", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("review_task_id", sa.Uuid(), nullable=False), sa.Column("actor_user_id", sa.Uuid(), nullable=False), sa.Column("action", sa.String(30), nullable=False), sa.Column("original_score", sa.Float(), nullable=False), sa.Column("final_score", sa.Float()), sa.Column("reason", sa.String(2000)), sa.Column("task_version", sa.Integer(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"]), sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]))
    op.create_table("grade_publications", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("attempt_id", sa.Uuid(), nullable=False), sa.Column("published_by_user_id", sa.Uuid(), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True), nullable=False), sa.ForeignKeyConstraint(["attempt_id"], ["student_attempts.id"]), sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]), sa.UniqueConstraint("attempt_id", name="uq_grade_publication_attempt"))
```

Use `sa.Uuid`, `sa.String`, `sa.Float`, `sa.Integer`, and timezone-aware `sa.DateTime` columns consistent with migration 0004. Define foreign keys to `attempt_answers`, `grading_runs`, `student_attempts`, and `users`; define the exact unique constraints and indexes above. Reverse all creates in `downgrade`.

- [ ] **Step 5: Run model and migration checks**

Run: `python -m pytest apps/api/tests/test_review_models.py -q`

Expected: PASS.

Run: `python -m alembic -c apps/api/alembic.ini upgrade head`

Expected: migration `0005_teacher_review_and_publication` applies without error against the configured database.

- [ ] **Step 6: Commit the domain schema**

```bash
git add apps/api/src/edu_grader_api/models.py apps/api/alembic/versions/0005_teacher_review_and_publication.py apps/api/tests/test_review_models.py
git commit -m "feat(api): add teacher review domain"
```

### Task 2: Create review tasks from submitted grading runs

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/assignments.py:370-560`
- Modify: `apps/api/tests/test_english_grading_runs.py:95-180`
- Modify: `apps/api/tests/test_assignments.py:260-310`

**Interfaces:**
- Consumes: `_persist_grading_run(session, answer, item, result) -> GradingRun`.
- Produces: `create_review_task_for_run(session, run: GradingRun) -> ReviewTask` in `services/reviews.py`, used in submission's transaction.

- [ ] **Step 1: Write failing submission tests**

```python
def test_submit_creates_one_open_task_for_a_review_required_run(session: Session) -> None:
    _, response = submit_attempt(session, tenant_id=student.tenant_id, student_id=student.id, assignment_id=assignment.id, idempotency_key=str(uuid4()), grader_client=FakeEnglishGraderClient())
    task = session.scalar(select(ReviewTask))
    assert task.reason is ReviewReason.NEEDS_REVIEW
    assert task.status is ReviewTaskStatus.OPEN
    assert task.grading_run.answer_snapshot_json == {"answer": "The road closure delayed them."}
    assert "score" not in response["grading"][0]


def test_submit_replay_does_not_create_a_second_review_task(session: Session) -> None:
    submit_attempt(session, tenant_id=student.tenant_id, student_id=student.id, assignment_id=assignment.id, idempotency_key=key, grader_client=FakeEnglishGraderClient())
    submit_attempt(session, tenant_id=student.tenant_id, student_id=student.id, assignment_id=assignment.id, idempotency_key=key, grader_client=FakeEnglishGraderClient())
    assert session.scalar(select(func.count(ReviewTask.id))) == 1
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_english_grading_runs.py -q`

Expected: assertions fail because no review task is created and the student receipt includes grading fields.

- [ ] **Step 3: Add task creation and student-safe receipt projection**

```python
def create_review_task_for_run(session: Session, run: GradingRun) -> ReviewTask:
    task = ReviewTask(
        attempt_answer=run.attempt_answer,
        grading_run=run,
        reason=(ReviewReason.NEEDS_REVIEW if run.requires_review else ReviewReason.AUTO_CONFIRMATION),
        status=ReviewTaskStatus.OPEN,
        active_key="open",
        version=0,
    )
    session.add(task)
    return task
```

Call this immediately after `_persist_grading_run`. Replace `_student_grading_summary` in the submission response with only `assignment_item_id`, `requires_review`, and student-safe feedback. Do not serialize score, maximum score, decision, rule snapshots, criteria, signals, or evidence before publication. Preserve the idempotent response snapshot unchanged on a replay. Review-list defaults exclude `auto_confirmation` until its batch endpoint selects those tasks.

- [ ] **Step 4: Run the focused test to verify it passes**

Run: `python -m pytest apps/api/tests/test_english_grading_runs.py apps/api/tests/test_assignments.py -q`

Expected: PASS with exactly one review task on an idempotent replay.

- [ ] **Step 5: Commit task creation and privacy boundary**

```bash
git add apps/api/src/edu_grader_api/services/assignments.py apps/api/src/edu_grader_api/services/reviews.py apps/api/tests/test_english_grading_runs.py apps/api/tests/test_assignments.py
git commit -m "feat(api): create review tasks on submission"
```

### Task 3: Add teacher queue, detail, and immutable decisions

**Files:**
- Create: `apps/api/src/edu_grader_api/services/reviews.py`
- Create: `apps/api/src/edu_grader_api/routers/reviews.py`
- Modify: `apps/api/src/edu_grader_api/main.py:1-25`
- Create: `apps/api/tests/test_reviews.py`

**Interfaces:**
- Consumes: `ReviewTask`, `ReviewDecision`, `GradingRun`, `Assignment`, `ClassTeacher`, and `AuditLog`.
- Produces: `list_review_tasks`, `get_review_task_detail`, `decide_review_task`, and `/v1/review-tasks` routes.

- [ ] **Step 1: Write failing queue, authorization, and decision tests**

```python
def test_assigned_teacher_filters_open_queue_by_class_assignment_subject_type_and_reason(api_client, session):
    task = make_review_task(session, subject="english", question_type="E4")
    response = api_client.get(
        "/v1/review-tasks",
        params={"class_id": str(task.class_id), "assignment_id": str(task.assignment_id),
                "subject": "english", "question_type": "E4", "reason": "needs_review"},
        headers=authorize(api_client, task.teacher),
    )
    assert response.status_code == 200
    assert response.json()["review_tasks"][0]["id"] == str(task.id)


def test_adjustment_requires_reason_and_rejects_stale_task_version(api_client, session):
    task = make_review_task(session)
    response = api_client.post(f"/v1/review-tasks/{task.id}/decisions", json={
        "action": "adjust_score", "score": 1, "reason": "equivalent answer", "version": 0,
    }, headers=authorize(api_client, task.teacher))
    stale = api_client.post(f"/v1/review-tasks/{task.id}/decisions", json={
        "action": "confirm", "version": 0,
    }, headers=authorize(api_client, task.teacher))
    assert response.status_code == 201
    assert stale.status_code == 409
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_reviews.py -q`

Expected: route lookup fails because the review router is not registered.

- [ ] **Step 3: Implement queue and detail services**

```python
def list_review_tasks(session: Session, *, tenant_id: UUID, teacher_id: UUID,
                      class_id: UUID | None, assignment_id: UUID | None,
                      subject: str | None, question_type: str | None,
                      reason: ReviewReason | None) -> list[ReviewTask]:
    statement = select(ReviewTask).join(AttemptAnswer).join(StudentAttempt).join(Assignment)
    statement = statement.join(AssignmentItem, AttemptAnswer.assignment_item_id == AssignmentItem.id)
    statement = statement.join(QuestionVersion, AssignmentItem.question_version_id == QuestionVersion.id)
    statement = statement.where(ReviewTask.status == ReviewTaskStatus.OPEN, Assignment.tenant_id == tenant_id)
    statement = statement.join(ClassTeacher, ClassTeacher.class_id == Assignment.class_id).where(ClassTeacher.teacher_id == teacher_id)
    if class_id is not None:
        statement = statement.where(Assignment.class_id == class_id)
    if assignment_id is not None:
        statement = statement.where(Assignment.id == assignment_id)
    if subject is not None:
        statement = statement.where(Assignment.subject == subject)
    if question_type is not None:
        statement = statement.where(QuestionVersion.question_type == question_type)
    if reason is not None:
        statement = statement.where(ReviewTask.reason == reason)
    else:
        statement = statement.where(ReviewTask.reason != ReviewReason.AUTO_CONFIRMATION)
    return list(session.scalars(statement.order_by(ReviewTask.created_at, ReviewTask.id)))
```

`get_review_task_detail` must return the original student answer, prompt, rule snapshot, automatic decision/score/confidence/evidence, ordered signals, and prior decisions. All access goes through the assignment's class-teacher membership.

- [ ] **Step 4: Implement decision transition service and router schemas**

```python
def decide_review_task(session: Session, *, task_id: UUID, tenant_id: UUID, teacher_id: UUID,
                       action: ReviewAction, version: int, score: float | None,
                       reason: str | None, grader_client: SubmissionGraderClient | None = None) -> ReviewDecision:
    task = get_teacher_review_task(session, task_id=task_id, tenant_id=tenant_id, teacher_id=teacher_id)
    if task.status is not ReviewTaskStatus.OPEN or task.version != version:
        raise ReviewConflictError()
    if action in {ReviewAction.ADJUST_SCORE, ReviewAction.REQUEST_REGRADE, ReviewAction.REPORT_RULE_PROBLEM} and not (reason and reason.strip()):
        raise ReviewValidationError("reason is required")
    if action is ReviewAction.ADJUST_SCORE and (score is None or not 0 <= score <= task.grading_run.max_score):
        raise ReviewValidationError("score is outside the grading range")
    decision = ReviewDecision(review_task=task, actor_user_id=teacher_id, action=action, original_score=task.grading_run.score, final_score=(score if action is ReviewAction.ADJUST_SCORE else task.grading_run.score), reason=reason.strip() if reason else None, task_version=version)
    if action is ReviewAction.REQUEST_REGRADE:
        rerun_review_task(session, task=task, grader_client=grader_client or HttpGraderClient(settings.grader_base_url))
        task.status, task.active_key = ReviewTaskStatus.SUPERSEDED, None
    else:
        task.status, task.active_key, task.resolved_at = ReviewTaskStatus.RESOLVED, None, utc_now()
    task.version += 1
    session.add(decision)
    _audit(session, tenant_id=tenant_id, actor_user_id=teacher_id, event_type="review.decision_recorded", target_type="review_task", target_id=task.id, metadata={"action": action.value, "task_version": version})
    return decision
```

`rerun_review_task` calls the grader with `task.grading_run.rule_snapshot_json` and `answer_snapshot_json`, persists a new immutable `GradingRun` for the same answer/item through `_persist_grading_run`, then calls `create_review_task_for_run` for the replacement. If the grader dependency fails, use `_dependency_review_result`; the replacement remains `needs_review` rather than losing the task.

Map `ReviewAccessError` to `404`, `ReviewConflictError` to `409`, and `ReviewValidationError` to `422`. Register the router in `main.py`. Return task version, final action, and decision ID; never expose this endpoint to students.

- [ ] **Step 5: Run queue and decision tests**

Run: `python -m pytest apps/api/tests/test_reviews.py -q`

Expected: PASS, including cross-tenant and unassigned-teacher `404`, mandatory reasons, immutable audit rows, duplicate decision `409`, and stale-version `409`.

- [ ] **Step 6: Commit teacher review operations**

```bash
git add apps/api/src/edu_grader_api/services/reviews.py apps/api/src/edu_grader_api/routers/reviews.py apps/api/src/edu_grader_api/main.py apps/api/tests/test_reviews.py
git commit -m "feat(api): add teacher review queue and decisions"
```

### Task 4: Batch-confirm deterministic work and publish final results

**Files:**
- Modify: `apps/api/src/edu_grader_api/services/reviews.py`
- Modify: `apps/api/src/edu_grader_api/routers/reviews.py`
- Modify: `apps/api/src/edu_grader_api/routers/assignments.py:222-270,313-350`
- Create: `apps/api/tests/test_grade_publication.py`

**Interfaces:**
- Consumes: `decide_review_task`, `ReviewTask`, `ReviewDecision`, `GradePublication`.
- Produces: `batch_confirm_deterministic`, `publish_attempt_results`, `published_student_grading`, and publication routes.

- [ ] **Step 1: Write failing batch and publication privacy tests**

```python
def test_batch_confirmation_rejects_subjective_and_review_required_tasks(api_client, session):
    task = make_review_task(session, question_type="E4")
    response = api_client.post(
        f"/v1/assignments/{task.assignment_id}/review-tasks/batch-confirm",
        json={"task_ids": [str(task.id)]}, headers=authorize(api_client, task.teacher),
    )
    assert response.status_code == 409


def test_student_cannot_read_score_or_evidence_until_teacher_publishes(api_client, session):
    student, task = make_resolved_review_task(session)
    before = api_client.get(f"/v1/student/assignments/{task.assignment_id}", headers=authorize(api_client, student))
    assert "score" not in str(before.json())
    published = api_client.post(
        f"/v1/assignments/{task.assignment_id}/attempts/{task.attempt_id}/publish-results",
        headers=authorize(api_client, task.teacher),
    )
    after = api_client.get(f"/v1/student/assignments/{task.assignment_id}", headers=authorize(api_client, student))
    assert published.status_code == 201
    assert after.json()["grading"][0] == {"assignment_item_id": str(task.item_id), "score": 1, "max_score": 1}
    assert "rule_snapshot" not in str(after.json())
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run: `python -m pytest apps/api/tests/test_grade_publication.py -q`

Expected: route lookup fails and the student response still exposes automatic grading data.

- [ ] **Step 3: Implement eligibility and batch confirmation**

```python
SUBJECTIVE_TYPES = frozenset({"E3", "E4"})

def batch_confirm_deterministic(session: Session, *, assignment_id: UUID, tenant_id: UUID,
                                teacher_id: UUID, task_ids: list[UUID]) -> list[ReviewDecision]:
    tasks = _open_teacher_tasks(session, assignment_id=assignment_id, tenant_id=tenant_id, teacher_id=teacher_id, task_ids=task_ids)
    if any(task.reason is not ReviewReason.AUTO_CONFIRMATION or task.grading_run.requires_review or task.grading_run.question_version.question_type in SUBJECTIVE_TYPES for task in tasks):
        raise ReviewConflictError()
    return [decide_review_task(session, task_id=task.id, tenant_id=tenant_id, teacher_id=teacher_id, action=ReviewAction.CONFIRM, version=task.version, score=None, reason=None) for task in tasks]

def can_publish_attempt(session: Session, attempt: StudentAttempt) -> bool:
    return all(task.status is ReviewTaskStatus.RESOLVED and task.reason != ReviewReason.REGRADE_REQUESTED for task in _latest_tasks_for_attempt(session, attempt.id))
```

Return `409` without partial handling if any requested task is ineligible. Ensure calling batch-confirm twice cannot create a second decision.

- [ ] **Step 4: Implement publication and bounded student result projection**

```python
def publish_attempt_results(session: Session, *, assignment_id: UUID, attempt_id: UUID,
                            tenant_id: UUID, teacher_id: UUID) -> GradePublication:
    assignment = get_teacher_assignment(session, tenant_id=tenant_id, teacher_id=teacher_id, assignment_id=assignment_id)
    attempt = get_assignment_attempt(session, assignment=assignment, attempt_id=attempt_id)
    if session.scalar(select(GradePublication).where(GradePublication.attempt_id == attempt.id)):
        raise ReviewConflictError()
    if not can_publish_attempt(session, attempt):
        raise ReviewConflictError()
    publication = GradePublication(attempt=attempt, published_by_user_id=teacher_id, published_at=utc_now())
    session.add(publication)
    _audit(session, tenant_id=tenant_id, actor_user_id=teacher_id, event_type="attempt.grades_published", target_type="student_attempt", target_id=attempt.id, metadata={"assignment_id": str(assignment_id)})
    return publication
```

In `get_student_assignment_route`, load the publication and set `grading` to an empty list before publication. After publication, call `published_student_grading` to return only assignment-item ID, final score, max score, and student-safe feedback. Do not alter the original `SubmissionReceipt` to disclose values on a later replay.

- [ ] **Step 5: Run publication tests**

Run: `python -m pytest apps/api/tests/test_grade_publication.py apps/api/tests/test_reviews.py apps/api/tests/test_english_grading_runs.py -q`

Expected: PASS; subjective/unreviewed attempts cannot publish, and scores appear only after a valid teacher publication.

- [ ] **Step 6: Commit publication controls**

```bash
git add apps/api/src/edu_grader_api/services/reviews.py apps/api/src/edu_grader_api/routers/reviews.py apps/api/src/edu_grader_api/routers/assignments.py apps/api/tests/test_grade_publication.py
git commit -m "feat(api): publish reviewed grades"
```

### Task 5: Run regression checks and document the deferred Issue #7 work

**Files:**
- Modify: `docs/superpowers/specs/2026-07-18-teacher-review-publication-design.md`
- Modify: `docs/superpowers/plans/2026-07-18-teacher-review-publication.md`

**Interfaces:**
- Consumes: completed review and publication API contracts.
- Produces: verified first-slice documentation with explicit follow-up boundaries.

- [ ] **Step 1: Add regression test for no unpublished score leak in submission replay**

```python
def test_submitted_receipt_never_reveals_score_after_later_publication(client, session):
    first = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=student_headers | {"Idempotency-Key": key})
    publish_attempt_results(session, assignment_id=assignment.id, attempt_id=attempt.id, tenant_id=student.tenant_id, teacher_id=teacher.id)
    replay = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=student_headers | {"Idempotency-Key": key})
    assert "score" not in str(first.json())
    assert replay.json() == first.json()
```

- [ ] **Step 2: Run the full API suite and lint**

Run: `python -m ruff format --check apps/api`

Expected: all API files already formatted.

Run: `python -m ruff check apps/api`

Expected: `All checks passed!`.

Run: `python -m pytest apps/api/tests -q`

Expected: all API tests pass.

Run: `git diff --check`

Expected: exit code `0`.

- [ ] **Step 3: Update design/plan checkboxes and deferred-boundary note**

```markdown
## Deferred Issue #7 scope

Student appeals, independent correction answers, and review analytics are intentionally not included in this first merge. They must consume immutable ReviewDecision and GradePublication rows rather than modifying GradingRun.
```

- [ ] **Step 4: Commit verification documentation**

```bash
git add docs/superpowers/specs/2026-07-18-teacher-review-publication-design.md docs/superpowers/plans/2026-07-18-teacher-review-publication.md apps/api/tests/test_grade_publication.py
git commit -m "test(api): verify review publication boundaries"
```
