from collections import Counter
from datetime import datetime, timezone
from statistics import median
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
    GradePublication,
    QuestionVersion,
    ReviewReason,
    ReviewAction,
    ReviewDecision,
    ReviewTask,
    ReviewTaskStatus,
    StudentAttempt,
    utc_now,
)
from ..settings import settings
from .grader import HttpGraderClient


class ReviewAccessError(Exception):
    """Raised when a teacher cannot access a review task."""


class ReviewConflictError(Exception):
    """Raised when a review task no longer accepts a decision."""


class ReviewValidationError(ValueError):
    """Raised when a decision payload is incomplete or invalid."""


def teacher_review_metrics(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    class_id: UUID | None = None,
    assignment_id: UUID | None = None,
) -> dict[str, object]:
    statement = (
        select(ReviewTask, ReviewDecision)
        .join(ReviewDecision, ReviewDecision.review_task_id == ReviewTask.id)
        .join(AttemptAnswer, ReviewTask.attempt_answer_id == AttemptAnswer.id)
        .join(StudentAttempt, AttemptAnswer.attempt_id == StudentAttempt.id)
        .join(Assignment, StudentAttempt.assignment_id == Assignment.id)
        .join(ClassTeacher, ClassTeacher.class_id == Assignment.class_id)
        .where(
            Assignment.tenant_id == tenant_id,
            ClassTeacher.teacher_id == teacher_id,
            ReviewDecision.actor_user_id == teacher_id,
            ReviewTask.status == ReviewTaskStatus.RESOLVED,
        )
    )
    if from_at is not None:
        statement = statement.where(ReviewDecision.created_at >= from_at)
    if to_at is not None:
        statement = statement.where(ReviewDecision.created_at <= to_at)
    if class_id is not None:
        statement = statement.where(Assignment.class_id == class_id)
    if assignment_id is not None:
        statement = statement.where(Assignment.id == assignment_id)

    rows = list(session.execute(statement))
    durations = [_duration_seconds(task.created_at, decision.created_at) for task, decision in rows]
    task_reasons = Counter(task.reason.value for task, _ in rows)
    decision_reasons = Counter(
        decision.reason.strip() for _, decision in rows if decision.reason and decision.reason.strip()
    )
    handled_tasks = len(rows)
    adjustments = sum(
        decision.action is ReviewAction.ADJUST_SCORE for _, decision in rows
    )
    return {
        "handled_tasks": handled_tasks,
        "average_duration_seconds": _rounded_average(durations),
        "median_duration_seconds": _rounded_median(durations),
        "score_adjustment_rate": adjustments / handled_tasks if handled_tasks else 0,
        "task_reasons": _reason_counts(task_reasons),
        "decision_reasons": _reason_counts(decision_reasons),
    }


def _duration_seconds(created_at: datetime, decided_at: datetime) -> float:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if decided_at.tzinfo is None:
        decided_at = decided_at.replace(tzinfo=timezone.utc)
    return max(0, (decided_at - created_at).total_seconds())


def _rounded_average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0


def _rounded_median(values: list[float]) -> float:
    return round(float(median(values)), 3) if values else 0


def _reason_counts(counts: Counter[str]) -> list[dict[str, object]]:
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


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
    grader_client: object | None = None,
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
    session.add(decision)
    if action is ReviewAction.REQUEST_REGRADE:
        _rerun_task(
            session,
            task=task,
            grader_client=grader_client or HttpGraderClient(settings.grader_base_url),
        )
        task.status = ReviewTaskStatus.SUPERSEDED
        task.active_key = None
    else:
        task.status = ReviewTaskStatus.RESOLVED
        task.active_key = None
        task.resolved_at = utc_now()
    task.version += 1
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


def _rerun_task(session: Session, *, task: ReviewTask, grader_client: object) -> None:
    from .assignments import _dependency_review_result, _persist_grading_run

    run = task.grading_run
    item = task.attempt_answer.assignment_item
    try:
        result = grader_client.grade(
            item.question_version.question_type,
            run.rule_snapshot_json,
            run.answer_snapshot_json,
            policy_version=run.policy_version,
        )
    except Exception as error:
        result = _dependency_review_result(run.rule_snapshot_json, error)
    replacement_run = _persist_grading_run(
        session, answer=task.attempt_answer, item=item, result=result
    )
    create_review_task_for_run(session, replacement_run)


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


def publish_attempt_results(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    assignment_id: UUID,
    attempt_id: UUID,
) -> GradePublication:
    attempt = session.scalar(
        select(StudentAttempt)
        .join(Assignment, StudentAttempt.assignment_id == Assignment.id)
        .join(ClassTeacher, ClassTeacher.class_id == Assignment.class_id)
        .where(
            StudentAttempt.id == attempt_id,
            Assignment.id == assignment_id,
            Assignment.tenant_id == tenant_id,
            ClassTeacher.teacher_id == teacher_id,
        )
    )
    if attempt is None:
        raise ReviewAccessError()
    if session.scalar(select(GradePublication).where(GradePublication.attempt_id == attempt.id)):
        raise ReviewConflictError()
    tasks = list(
        session.scalars(
            select(ReviewTask)
            .join(AttemptAnswer, ReviewTask.attempt_answer_id == AttemptAnswer.id)
            .where(AttemptAnswer.attempt_id == attempt.id)
        )
    )
    if not tasks or any(task.status is not ReviewTaskStatus.RESOLVED for task in tasks):
        raise ReviewConflictError()
    publication = GradePublication(attempt=attempt, published_by_user_id=teacher_id)
    session.add(publication)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=teacher_id,
            event_type="attempt.grades_published",
            target_type="student_attempt",
            target_id=attempt.id,
            metadata_json={"assignment_id": str(assignment_id)},
        )
    )
    return publication


def published_student_grading(session: Session, *, attempt_id: UUID) -> list[dict[str, object]]:
    answers = list(
        session.scalars(
            select(AttemptAnswer)
            .join(AssignmentItem, AttemptAnswer.assignment_item_id == AssignmentItem.id)
            .where(AttemptAnswer.attempt_id == attempt_id)
            .order_by(AssignmentItem.position)
        )
    )
    results: list[dict[str, object]] = []
    for answer in answers:
        task = session.scalar(
            select(ReviewTask)
            .where(ReviewTask.attempt_answer_id == answer.id)
            .order_by(ReviewTask.created_at.desc())
        )
        if task is None:
            continue
        decision = task.decisions[-1] if task.decisions else None
        feedback = task.grading_run.evidence_json.get("feedback")
        results.append(
            {
                "assignment_item_id": str(answer.assignment_item_id),
                "score": decision.final_score if decision is not None else task.grading_run.score,
                "max_score": task.grading_run.max_score,
                "feedback": feedback if isinstance(feedback, list) else [],
            }
        )
    return results
