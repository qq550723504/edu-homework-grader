from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    AssignmentItem,
    AttemptAnswer,
    ClassTeacher,
    GradingRun,
    QuestionVersion,
    ReviewReason,
    ReviewTask,
    ReviewTaskStatus,
    StudentAttempt,
)


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
