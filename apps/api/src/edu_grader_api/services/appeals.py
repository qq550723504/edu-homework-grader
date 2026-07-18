from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AppealStatus, GradePublication, ReviewAppeal, StudentAttempt


class AppealAccessError(Exception):
    pass


class AppealConflictError(Exception):
    pass


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
