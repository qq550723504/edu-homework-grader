from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    AssignmentItem,
    AttemptAnswer,
    AuditLog,
    ClassTeacher,
    GradingRun,
    QuestionVersion,
    ReviewReason,
    ReviewAction,
    ReviewDecision,
    ReviewTask,
    ReviewTaskStatus,
    StudentAttempt,
    utc_now,
)


class ReviewAccessError(Exception):
    """Raised when a teacher cannot access a review task."""


class ReviewConflictError(Exception):
    """Raised when a review task no longer accepts a decision."""


class ReviewValidationError(ValueError):
    """Raised when a decision payload is incomplete or invalid."""


def create_review_task_for_run(session: Session, run: GradingRun) -> ReviewTask:
    task = ReviewTask(
        attempt_answer=run.attempt_answer,
        grading_run=run,
        reason=(
            ReviewReason.NEEDS_REVIEW if run.requires_review else ReviewReason.AUTO_CONFIRMATION
        ),
        status=ReviewTaskStatus.OPEN,
        active_key="open",
        version=0,
    )
    session.add(task)
    return task


def list_teacher_review_tasks(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    class_id: UUID | None = None,
    assignment_id: UUID | None = None,
    subject: str | None = None,
    question_type: str | None = None,
    reason: ReviewReason | None = None,
) -> list[ReviewTask]:
    statement = (
        select(ReviewTask)
        .join(AttemptAnswer, ReviewTask.attempt_answer_id == AttemptAnswer.id)
        .join(StudentAttempt, AttemptAnswer.attempt_id == StudentAttempt.id)
        .join(Assignment, StudentAttempt.assignment_id == Assignment.id)
        .join(AssignmentItem, AttemptAnswer.assignment_item_id == AssignmentItem.id)
        .join(QuestionVersion, AssignmentItem.question_version_id == QuestionVersion.id)
        .join(ClassTeacher, ClassTeacher.class_id == Assignment.class_id)
        .where(
            Assignment.tenant_id == tenant_id,
            ClassTeacher.teacher_id == teacher_id,
            ReviewTask.status == ReviewTaskStatus.OPEN,
        )
    )
    if class_id is not None:
        statement = statement.where(Assignment.class_id == class_id)
    if assignment_id is not None:
        statement = statement.where(Assignment.id == assignment_id)
    if subject is not None:
        statement = statement.where(Assignment.subject == subject)
    if question_type is not None:
        statement = statement.where(QuestionVersion.question_type == question_type)
    if reason is None:
        statement = statement.where(ReviewTask.reason != ReviewReason.AUTO_CONFIRMATION)
    else:
        statement = statement.where(ReviewTask.reason == reason)
    return list(session.scalars(statement.order_by(ReviewTask.created_at, ReviewTask.id)))


def get_teacher_review_task(
    session: Session, *, tenant_id: UUID, teacher_id: UUID, task_id: UUID
) -> ReviewTask:
    task = session.scalar(
        select(ReviewTask)
        .join(AttemptAnswer, ReviewTask.attempt_answer_id == AttemptAnswer.id)
        .join(StudentAttempt, AttemptAnswer.attempt_id == StudentAttempt.id)
        .join(Assignment, StudentAttempt.assignment_id == Assignment.id)
        .join(ClassTeacher, ClassTeacher.class_id == Assignment.class_id)
        .where(
            ReviewTask.id == task_id,
            Assignment.tenant_id == tenant_id,
            ClassTeacher.teacher_id == teacher_id,
        )
    )
    if task is None:
        raise ReviewAccessError()
    return task


def decide_review_task(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    task_id: UUID,
    action: ReviewAction,
    version: int,
    score: float | None,
    reason: str | None,
) -> ReviewDecision:
    task = get_teacher_review_task(
        session, tenant_id=tenant_id, teacher_id=teacher_id, task_id=task_id
    )
    if task.status is not ReviewTaskStatus.OPEN or task.version != version:
        raise ReviewConflictError()
    normalized_reason = reason.strip() if reason is not None else ""
    requires_reason = {
        ReviewAction.ADJUST_SCORE,
        ReviewAction.REQUEST_REGRADE,
        ReviewAction.REPORT_RULE_PROBLEM,
    }
    if action in requires_reason and not normalized_reason:
        raise ReviewValidationError("reason is required")
    if action is ReviewAction.ADJUST_SCORE:
        if score is None or not 0 <= score <= task.grading_run.max_score:
            raise ReviewValidationError("score is outside the grading range")
        final_score = score
    else:
        final_score = task.grading_run.score
    decision = ReviewDecision(
        review_task=task,
        actor_user_id=teacher_id,
        action=action,
        original_score=task.grading_run.score,
        final_score=final_score,
        reason=normalized_reason or None,
        task_version=version,
    )
    task.status = ReviewTaskStatus.RESOLVED
    task.active_key = None
    task.resolved_at = utc_now()
    task.version += 1
    session.add(decision)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=teacher_id,
            event_type="review.decision_recorded",
            target_type="review_task",
            target_id=task.id,
            metadata_json={"action": action.value, "task_version": version},
        )
    )
    session.flush()
    return decision


def batch_confirm_deterministic(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    assignment_id: UUID,
    task_ids: list[UUID],
) -> list[ReviewDecision]:
    tasks = [
        get_teacher_review_task(
            session, tenant_id=tenant_id, teacher_id=teacher_id, task_id=task_id
        )
        for task_id in task_ids
    ]
    for task in tasks:
        question_type = task.grading_run.question_version.question_type
        if (
            task.attempt_answer.attempt.assignment_id != assignment_id
            or task.reason is not ReviewReason.AUTO_CONFIRMATION
            or task.grading_run.requires_review
            or question_type in {"E3", "E4"}
        ):
            raise ReviewConflictError()
    return [
        decide_review_task(
            session,
            tenant_id=tenant_id,
            teacher_id=teacher_id,
            task_id=task.id,
            action=ReviewAction.CONFIRM,
            version=task.version,
            score=None,
            reason=None,
        )
        for task in tasks
    ]
