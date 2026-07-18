from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    AppealStatus,
    Assignment,
    ClassTeacher,
    CorrectionAttempt,
    GradePublication,
    ReviewAppeal,
    StudentAttempt,
    utc_now,
)


class AppealAccessError(Exception):
    pass


class AppealConflictError(Exception):
    pass


def decide_appeal(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    appeal_id: UUID,
    approve: bool,
    version: int,
) -> CorrectionAttempt | None:
    appeal = session.scalar(select(ReviewAppeal).where(ReviewAppeal.id == appeal_id))
    if appeal is None:
        raise AppealAccessError()
    original = session.get(StudentAttempt, appeal.original_attempt_id)
    assignment = session.get(Assignment, original.assignment_id) if original is not None else None
    if (
        assignment is None
        or assignment.tenant_id != tenant_id
        or session.get(ClassTeacher, (assignment.class_id, teacher_id)) is None
    ):
        raise AppealAccessError()
    if appeal.status is not AppealStatus.OPEN or appeal.version != version:
        raise AppealConflictError()
    appeal.version += 1
    appeal.decided_by_user_id = teacher_id
    appeal.decided_at = utc_now()
    if not approve:
        appeal.status = AppealStatus.REJECTED
        return None
    correction = StudentAttempt(
        tenant_id=tenant_id,
        assignment_id=original.assignment_id,
        student_id=original.student_id,
        attempt_number=original.attempt_number + 1,
    )
    session.add(correction)
    session.flush()
    link = CorrectionAttempt(
        original_attempt_id=original.id, correction_attempt_id=correction.id, appeal_id=appeal.id
    )
    session.add(link)
    appeal.status = AppealStatus.APPROVED
    return link


def create_student_appeal(
    session: Session, *, tenant_id: UUID, student_id: UUID, attempt_id: UUID, reason: str
) -> ReviewAppeal:
    attempt = session.scalar(
        select(StudentAttempt).where(
            StudentAttempt.id == attempt_id,
            StudentAttempt.tenant_id == tenant_id,
            StudentAttempt.student_id == student_id,
        )
    )
    if (
        attempt is None
        or session.scalar(
            select(GradePublication.id).where(GradePublication.attempt_id == attempt_id)
        )
        is None
    ):
        raise AppealAccessError()
    if (
        session.scalar(
            select(ReviewAppeal.id).where(
                ReviewAppeal.original_attempt_id == attempt_id,
                ReviewAppeal.status == AppealStatus.OPEN,
            )
        )
        is not None
    ):
        raise AppealConflictError()
    appeal = ReviewAppeal(original_attempt_id=attempt_id, student_id=student_id, reason=reason)
    session.add(appeal)
    session.flush()
    return appeal
