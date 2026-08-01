import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    AuditLog,
    Base,
    Classroom,
    ClassTeacher,
    Enrollment,
    Role,
    StudentGuardianConsent,
    Tenant,
    User,
)
from edu_grader_api.services import customer_provisioning
from edu_grader_api.services.customer_provisioning import provision_customer
from edu_grader_api.services.roster import parse_roster

ROSTER = b"""class_code,class_name,student_school_id,student_display_name,student_under_14,guardian_consent_status,guardian_consent_notice_version,guardian_consent_evidence_reference
7A,Class 7A,S-001,Ada Lovelace,false,not_required,,
7A,Class 7A,S-002,Grace Hopper,false,not_required,,
"""


def test_customer_provisioning_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    rows = parse_roster(ROSTER)

    with Session(engine) as session:
        first = provision_customer(
            session,
            tenant_slug="acme",
            tenant_name="Acme School",
            oidc_issuer="https://id.example.test/realms/edu",
            operator_subject="operator-1",
            teacher_subject="teacher-1",
            teacher_display_name="Teacher One",
            teacher_email="teacher@example.test",
            rows=rows,
        )
        second = provision_customer(
            session,
            tenant_slug="acme",
            tenant_name="Acme School",
            oidc_issuer="https://id.example.test/realms/edu",
            operator_subject="operator-1",
            teacher_subject="teacher-1",
            teacher_display_name="Teacher One Updated",
            teacher_email="teacher@example.test",
            rows=rows,
        )

        assert first.tenant_id == second.tenant_id
        assert first.teacher_id == second.teacher_id
        assert session.scalar(select(func.count(Tenant.id))) == 1
        assert session.scalar(select(func.count(User.id))) == 4
        assert session.scalar(select(func.count(Classroom.id))) == 1
        assert session.scalar(select(func.count(ClassTeacher.teacher_id))) == 1
        assert session.scalar(select(func.count(Enrollment.student_id))) == 2
        teacher = session.get(User, first.teacher_id)
        assert teacher is not None
        assert teacher.display_name == "Teacher One Updated"
        assert teacher.role is Role.TEACHER
        operator = session.scalar(select(User).where(User.oidc_subject == "operator-1"))
        assert operator is not None
        assert operator.role is Role.ADMIN
        consent = session.scalar(
            select(StudentGuardianConsent).where(StudentGuardianConsent.student_id != teacher.id)
        )
        assert consent is not None
        assert consent.version == 0
        assert session.scalar(select(func.count(AuditLog.id))) == 4


def test_customer_provisioning_rolls_back_when_roster_import_fails(monkeypatch) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    rows = parse_roster(ROSTER)

    def fail_import(*args, **kwargs):
        raise RuntimeError("roster import failed")

    monkeypatch.setattr(customer_provisioning, "_import_roster_rows", fail_import)
    with Session(engine) as session:
        with pytest.raises(RuntimeError, match="roster import failed"):
            provision_customer(
                session,
                tenant_slug="acme",
                tenant_name="Acme School",
                oidc_issuer="https://id.example.test/realms/edu",
                operator_subject="operator-1",
                teacher_subject="teacher-1",
                teacher_display_name="Teacher One",
                teacher_email="teacher@example.test",
                rows=rows,
            )
        assert session.scalar(select(func.count(Tenant.id))) == 0
        assert session.scalar(select(func.count(User.id))) == 0
        assert session.scalar(select(func.count(Classroom.id))) == 0
