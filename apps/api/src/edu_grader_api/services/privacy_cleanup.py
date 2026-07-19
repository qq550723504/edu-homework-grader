from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import (
    AttemptAnswer,
    CorrectionAttempt,
    Enrollment,
    GradePublication,
    GradingRun,
    GradingSignal,
    PrivacyRequest,
    PrivacyRequestStatus,
    ReviewAppeal,
    ReviewDecision,
    ReviewTask,
    Role,
    StudentAttempt,
    StudentGuardianConsent,
    SubmissionReceipt,
    User,
)


class PrivacyCleanupError(ValueError):
    pass


class PrivacyCleanupSkipped(PrivacyCleanupError):
    pass


@dataclass(frozen=True)
class CleanupResult:
    request_id: UUID
    status: PrivacyRequestStatus


def eligible_privacy_requests(session: Session, *, now: datetime) -> list[PrivacyRequest]:
    return list(
        session.scalars(
            select(PrivacyRequest)
            .where(
                PrivacyRequest.status == PrivacyRequestStatus.APPROVED,
                PrivacyRequest.eligible_for_deletion_at.is_not(None),
                PrivacyRequest.eligible_for_deletion_at <= now,
            )
            .order_by(PrivacyRequest.eligible_for_deletion_at, PrivacyRequest.id)
        )
    )


def complete_privacy_request(
    session: Session,
    *,
    request_id: UUID,
    actor_user_id: UUID,
    now: datetime,
) -> CleanupResult:
    request = session.scalar(
        select(PrivacyRequest).where(PrivacyRequest.id == request_id).with_for_update()
    )
    if request is None or request.status is not PrivacyRequestStatus.APPROVED:
        raise PrivacyCleanupSkipped("privacy request is not approved")
    if request.eligible_for_deletion_at is None or _as_utc(request.eligible_for_deletion_at) > now:
        raise PrivacyCleanupSkipped("privacy request is not eligible")
    actor = session.scalar(
        select(User).where(
            User.id == actor_user_id,
            User.tenant_id == request.tenant_id,
            User.role == Role.ADMIN,
        )
    )
    if actor is None:
        raise PrivacyCleanupError("cleanup actor is not a tenant administrator")
    student = session.scalar(
        select(User).where(
            User.id == request.student_id,
            User.tenant_id == request.tenant_id,
            User.role == Role.STUDENT,
        )
    )
    if student is None:
        raise PrivacyCleanupSkipped("student is unavailable for cleanup")

    attempt_ids = select(StudentAttempt.id).where(StudentAttempt.student_id == student.id)
    answer_ids = select(AttemptAnswer.id).where(AttemptAnswer.attempt_id.in_(attempt_ids))
    run_ids = select(GradingRun.id).where(GradingRun.attempt_answer_id.in_(answer_ids))
    task_ids = select(ReviewTask.id).where(ReviewTask.attempt_answer_id.in_(answer_ids))

    session.execute(delete(ReviewDecision).where(ReviewDecision.review_task_id.in_(task_ids)))
    session.execute(delete(GradingSignal).where(GradingSignal.grading_run_id.in_(run_ids)))
    session.execute(delete(ReviewTask).where(ReviewTask.id.in_(task_ids)))
    session.execute(delete(GradePublication).where(GradePublication.attempt_id.in_(attempt_ids)))
    session.execute(
        delete(CorrectionAttempt).where(
            or_(
                CorrectionAttempt.original_attempt_id.in_(attempt_ids),
                CorrectionAttempt.correction_attempt_id.in_(attempt_ids),
            )
        )
    )
    session.execute(delete(ReviewAppeal).where(ReviewAppeal.student_id == student.id))
    session.execute(delete(GradingRun).where(GradingRun.id.in_(run_ids)))
    session.execute(delete(AttemptAnswer).where(AttemptAnswer.id.in_(answer_ids)))
    session.execute(delete(SubmissionReceipt).where(SubmissionReceipt.student_id == student.id))
    session.execute(delete(StudentAttempt).where(StudentAttempt.id.in_(attempt_ids)))
    session.execute(delete(Enrollment).where(Enrollment.student_id == student.id))
    session.execute(delete(StudentGuardianConsent).where(StudentGuardianConsent.student_id == student.id))

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
    return CleanupResult(request_id=request.id, status=request.status)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
