import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    GuardianConsentStatus,
    Role,
    StudentGuardianConsent,
    Tenant,
    User,
)


def test_guardian_consent_table_and_statuses_are_registered() -> None:
    assert GuardianConsentStatus.NOT_REQUIRED.value == "not_required"
    assert GuardianConsentStatus.PENDING.value == "pending"
    assert GuardianConsentStatus.GRANTED.value == "granted"
    assert GuardianConsentStatus.WITHDRAWN.value == "withdrawn"
    assert StudentGuardianConsent.__tablename__ in Base.metadata.tables


def test_guardian_consent_is_unique_per_student() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        student = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Student",
        )
        session.add_all([tenant, student])
        session.flush()
        session.add_all(
            [
                StudentGuardianConsent(
                    student_id=student.id,
                    requires_guardian_consent=True,
                    status=GuardianConsentStatus.PENDING,
                ),
                StudentGuardianConsent(
                    student_id=student.id,
                    requires_guardian_consent=True,
                    status=GuardianConsentStatus.PENDING,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_not_required_consent_needs_no_evidence() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        student = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Student",
        )
        session.add_all([tenant, student])
        session.flush()
        session.add(
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=False,
                status=GuardianConsentStatus.NOT_REQUIRED,
            )
        )

        session.commit()
