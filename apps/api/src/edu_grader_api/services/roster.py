import csv
import re
from collections.abc import Callable
from dataclasses import dataclass
from io import StringIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..models import (
    Classroom,
    Enrollment,
    GuardianConsentStatus,
    Role,
    StudentGuardianConsent,
    User,
    utc_now,
)


EXPECTED_HEADERS = {
    "class_code",
    "class_name",
    "student_school_id",
    "student_display_name",
    "student_under_14",
    "guardian_consent_status",
    "guardian_consent_notice_version",
    "guardian_consent_evidence_reference",
}
REQUIRED_HEADERS = {
    "class_code",
    "class_name",
    "student_school_id",
    "student_display_name",
    "student_under_14",
    "guardian_consent_status",
}
SENSITIVE_EVIDENCE_REFERENCE = re.compile(r"@|\d{11,}|[\x00-\x1f\x7f]")


class RosterValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RosterRow:
    class_code: str
    class_name: str
    student_school_id: str
    student_display_name: str
    requires_guardian_consent: bool
    guardian_consent_status: GuardianConsentStatus
    guardian_consent_notice_version: str | None
    guardian_consent_evidence_reference: str | None


def parse_required_boolean(value: str, row_number: int) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise RosterValidationError(f"row {row_number} has an invalid student_under_14 value")


def parse_consent_status(value: str, row_number: int) -> GuardianConsentStatus:
    try:
        return GuardianConsentStatus(value)
    except ValueError as error:
        raise RosterValidationError(
            f"row {row_number} has an invalid guardian_consent_status"
        ) from error


def validate_consent_fields(
    *,
    row_number: int,
    requires_guardian_consent: bool,
    status: GuardianConsentStatus,
    notice_version: str,
    evidence_reference: str,
) -> None:
    if not requires_guardian_consent:
        if status != GuardianConsentStatus.NOT_REQUIRED:
            raise RosterValidationError(
                f"row {row_number} must use not_required when student_under_14 is false"
            )
        if notice_version or evidence_reference:
            raise RosterValidationError(
                f"row {row_number} must not include guardian consent details when not required"
            )
        return

    if status == GuardianConsentStatus.NOT_REQUIRED:
        raise RosterValidationError(
            f"row {row_number} cannot use not_required when student_under_14 is true"
        )
    if status != GuardianConsentStatus.GRANTED:
        if notice_version or evidence_reference:
            raise RosterValidationError(
                f"row {row_number} must only include guardian consent details for granted consent"
            )
        return
    if not notice_version or not evidence_reference:
        raise RosterValidationError(
            f"row {row_number} requires notice version and evidence reference for granted consent"
        )
    if len(notice_version) > 50 or len(evidence_reference) > 100:
        raise RosterValidationError(f"row {row_number} has oversized guardian consent details")
    if SENSITIVE_EVIDENCE_REFERENCE.search(evidence_reference):
        raise RosterValidationError(f"row {row_number} has an invalid evidence reference")


def parse_roster(data: bytes) -> list[RosterRow]:
    try:
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise RosterValidationError("CSV must be UTF-8") from error
    if set(reader.fieldnames or []) != EXPECTED_HEADERS:
        raise RosterValidationError("CSV has invalid headers")

    rows: list[RosterRow] = []
    seen_students: set[str] = set()
    class_names: dict[str, str] = {}
    for row_number, record in enumerate(reader, start=2):
        values = {key: (record.get(key) or "").strip() for key in EXPECTED_HEADERS}
        if not all(values[key] for key in REQUIRED_HEADERS):
            raise RosterValidationError(f"row {row_number} has a blank required value")
        student_id = values["student_school_id"]
        if student_id in seen_students:
            raise RosterValidationError(f"row {row_number} repeats student_school_id")
        seen_students.add(student_id)
        code = values["class_code"]
        if code in class_names and class_names[code] != values["class_name"]:
            raise RosterValidationError(f"row {row_number} conflicts with the class name")
        class_names[code] = values["class_name"]
        requires_guardian_consent = parse_required_boolean(values["student_under_14"], row_number)
        consent_status = parse_consent_status(values["guardian_consent_status"], row_number)
        notice_version = values["guardian_consent_notice_version"] or None
        evidence_reference = values["guardian_consent_evidence_reference"] or None
        validate_consent_fields(
            row_number=row_number,
            requires_guardian_consent=requires_guardian_consent,
            status=consent_status,
            notice_version=notice_version or "",
            evidence_reference=evidence_reference or "",
        )
        rows.append(
            RosterRow(
                class_code=code,
                class_name=values["class_name"],
                student_school_id=student_id,
                student_display_name=values["student_display_name"],
                requires_guardian_consent=requires_guardian_consent,
                guardian_consent_status=consent_status,
                guardian_consent_notice_version=notice_version,
                guardian_consent_evidence_reference=evidence_reference,
            )
        )
    if not rows:
        raise RosterValidationError("CSV has no data rows")
    return rows


def import_roster(
    session: Session,
    actor: CurrentPrincipal,
    rows: list[RosterRow],
    existing_student_guard: Callable[[Session, User, RosterRow], None] | None = None,
) -> int:
    """Atomically create tenant-local roster records and their audit events."""
    session.rollback()
    with session.begin():
        for row in rows:
            classroom = session.scalar(
                select(Classroom).where(
                    Classroom.tenant_id == UUID(actor.tenant_id), Classroom.code == row.class_code
                )
            )
            if classroom is None:
                classroom = Classroom(
                    tenant_id=UUID(actor.tenant_id), code=row.class_code, name=row.class_name
                )
                session.add(classroom)
                session.flush()

            student = session.scalar(
                select(User).where(
                    User.tenant_id == UUID(actor.tenant_id), User.school_id == row.student_school_id
                )
            )
            if student is None:
                student = User(
                    tenant_id=UUID(actor.tenant_id),
                    role=Role.STUDENT,
                    school_id=row.student_school_id,
                    display_name=row.student_display_name,
                )
                session.add(student)
                session.flush()
            else:
                if existing_student_guard is not None:
                    existing_student_guard(session, student, row)
                student.display_name = row.student_display_name

            consent = session.get(StudentGuardianConsent, student.id)
            previous_status = consent.status if consent is not None else None
            if consent is None:
                consent = StudentGuardianConsent(
                    student_id=student.id,
                    requires_guardian_consent=row.requires_guardian_consent,
                    status=row.guardian_consent_status,
                )
                session.add(consent)
            else:
                consent.requires_guardian_consent = row.requires_guardian_consent
                consent.status = row.guardian_consent_status
                consent.version += 1
            consent.notice_version = row.guardian_consent_notice_version
            consent.evidence_reference = row.guardian_consent_evidence_reference
            consent.verified_by_user_id = UUID(actor.user_id)
            if row.guardian_consent_status == GuardianConsentStatus.GRANTED:
                if previous_status != GuardianConsentStatus.GRANTED:
                    consent.granted_at = utc_now()
                consent.withdrawn_at = None
                consent.withdrawal_reason = None
            elif row.guardian_consent_status == GuardianConsentStatus.WITHDRAWN:
                if previous_status != GuardianConsentStatus.WITHDRAWN:
                    consent.withdrawn_at = utc_now()
            else:
                consent.granted_at = None
                consent.withdrawn_at = None
                consent.withdrawal_reason = None

            enrollment = session.get(Enrollment, (classroom.id, student.id))
            if enrollment is None:
                session.add(Enrollment(class_id=classroom.id, student_id=student.id))
            append_audit_event(
                session,
                tenant_id=UUID(actor.tenant_id),
                actor_user_id=UUID(actor.user_id),
                event_type="roster.imported",
                target_type="student",
                target_id=student.id,
                metadata={
                    "class_id": str(classroom.id),
                    "guardian_consent_status": row.guardian_consent_status.value,
                },
            )
            append_audit_event(
                session,
                tenant_id=UUID(actor.tenant_id),
                actor_user_id=UUID(actor.user_id),
                event_type="guardian_consent.imported",
                target_type="student",
                target_id=student.id,
                metadata={
                    "status": row.guardian_consent_status.value,
                    "notice_version": row.guardian_consent_notice_version,
                    "evidence_reference": row.guardian_consent_evidence_reference,
                    "version": consent.version,
                },
            )
    return len(rows)


def import_teacher_roster(
    session: Session,
    actor: CurrentPrincipal,
    class_id: UUID,
    rows: list[RosterRow],
) -> int:
    """Import a roster without allowing teachers to alter students in other classes."""

    def guard_existing_student(active_session: Session, student: User, _: RosterRow) -> None:
        active_session.execute(select(User.id).where(User.id == student.id).with_for_update())
        enrollment_class_ids = set(
            active_session.scalars(
                select(Enrollment.class_id)
                .where(Enrollment.student_id == student.id)
                .with_for_update()
            ).all()
        )
        if enrollment_class_ids != {class_id}:
            raise RosterValidationError("student_school_id already belongs to a different class")

    return import_roster(
        session,
        actor,
        rows,
        existing_student_guard=guard_existing_student,
    )
