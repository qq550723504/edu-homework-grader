from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import GuardianConsentStatus, Role, StudentGuardianConsent, User


@dataclass(frozen=True)
class GuardianConsentIntegrityReport:
    missing_student_ids: tuple[UUID, ...]
    contradictory_student_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GuardianConsentRepairResult:
    created_student_ids: tuple[UUID, ...]


def inspect_guardian_consent_integrity(session: Session) -> GuardianConsentIntegrityReport:
    missing_student_ids = tuple(
        session.scalars(
            select(User.id)
            .outerjoin(StudentGuardianConsent, StudentGuardianConsent.student_id == User.id)
            .where(User.role == Role.STUDENT, StudentGuardianConsent.student_id.is_(None))
            .order_by(User.id)
        )
    )
    contradictory_student_ids = tuple(
        session.scalars(
            select(StudentGuardianConsent.student_id)
            .join(User, User.id == StudentGuardianConsent.student_id)
            .where(
                User.role == Role.STUDENT,
                StudentGuardianConsent.requires_guardian_consent.is_(True),
                StudentGuardianConsent.status == GuardianConsentStatus.NOT_REQUIRED,
            )
            .order_by(StudentGuardianConsent.student_id)
        )
    )
    return GuardianConsentIntegrityReport(
        missing_student_ids=missing_student_ids,
        contradictory_student_ids=contradictory_student_ids,
    )


def repair_missing_guardian_consents(session: Session) -> GuardianConsentRepairResult:
    students = list(
        session.scalars(
            select(User)
            .outerjoin(StudentGuardianConsent, StudentGuardianConsent.student_id == User.id)
            .where(User.role == Role.STUDENT, StudentGuardianConsent.student_id.is_(None))
            .order_by(User.id)
            .with_for_update()
        )
    )
    for student in students:
        session.add(
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=True,
                status=GuardianConsentStatus.PENDING,
            )
        )
        append_audit_event(
            session,
            tenant_id=student.tenant_id,
            actor_user_id=None,
            event_type="guardian_consent.repair_created_pending",
            target_type="student",
            target_id=student.id,
            metadata={"reason": "missing_record"},
        )
    return GuardianConsentRepairResult(
        created_student_ids=tuple(student.id for student in students)
    )
