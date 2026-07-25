from datetime import timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.db import Base
from edu_grader_api.models import (
    Classroom,
    ClassTeacher,
    Role,
    StudentActivation,
    StudentActivationStatus,
    Tenant,
    User,
    utc_now,
)


def test_activation_code_hmac_is_deterministic_and_not_plaintext(monkeypatch) -> None:
    from edu_grader_api.services.student_activations import activation_code_hmac

    monkeypatch.setattr("edu_grader_api.services.student_activations.settings.student_activation_hmac_key", "k" * 32)

    fingerprint = activation_code_hmac("one-time-code")

    assert fingerprint != "one-time-code"
    assert len(fingerprint) == 64
    assert fingerprint == activation_code_hmac("one-time-code")


def test_generated_activation_codes_are_url_safe_and_unique() -> None:
    from edu_grader_api.services.student_activations import generate_activation_code

    first = generate_activation_code()
    second = generate_activation_code()

    assert first != second
    assert len(first) >= 32
    assert all(character.isalnum() or character in "-_" for character in first)


def test_issue_activation_persists_only_hmac_after_keycloak_provisioning() -> None:
    from edu_grader_api.services.student_activations import issue_activation

    class FakeKeycloak:
        def ensure_student(self, *, school_id: str, display_name: str, activation_code: str) -> str:
            assert school_id == "S-001"
            assert activation_code
            return "kc-1"

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        teacher = User(tenant=tenant, role=Role.TEACHER, oidc_issuer="https://issuer.example.test", oidc_subject="teacher-1", display_name="Teacher", work_email="teacher@example.test")
        student = User(tenant=tenant, role=Role.STUDENT, school_id="S-001", display_name="Ada")
        classroom = Classroom(tenant=tenant, code="7A", name="Year 7 A")
        session.add_all([tenant, teacher, student, classroom])
        session.commit()

        activation_code = issue_activation(session, teacher=teacher, classroom=classroom, student=student, keycloak=FakeKeycloak(), now=utc_now())

        activation = session.get(StudentActivation, activation_code.activation_id)
        assert activation is not None
        assert activation.status is StudentActivationStatus.ISSUED
        assert activation.code_hmac != activation_code.code
        assert activation.keycloak_user_id == "kc-1"


def test_issued_activation_persists_lifecycle_and_relationships() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        teacher = User(
            tenant=tenant,
            role=Role.TEACHER,
            oidc_issuer="https://issuer.example.test",
            oidc_subject="teacher-1",
            display_name="Teacher",
            work_email="teacher@example.test",
        )
        student = User(tenant=tenant, role=Role.STUDENT, school_id="S-001", display_name="Ada")
        classroom = Classroom(tenant=tenant, code="7A", name="Year 7 A")
        session.add_all([tenant, teacher, student, classroom])
        session.flush()
        session.add(ClassTeacher(class_id=classroom.id, teacher_id=teacher.id))
        now = utc_now()
        activation = StudentActivation(
            student_id=student.id,
            class_id=classroom.id,
            keycloak_user_id="keycloak-user-1",
            code_hmac="a" * 64,
            status=StudentActivationStatus.ISSUED,
            issued_at=now,
            expires_at=now + timedelta(days=7),
            issued_by_user_id=teacher.id,
            request_id=uuid4(),
        )
        session.add(activation)
        session.commit()

        assert activation.status is StudentActivationStatus.ISSUED
        assert student.activations == [activation]
        assert classroom.student_activations == [activation]
