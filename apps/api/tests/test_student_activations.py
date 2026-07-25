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
