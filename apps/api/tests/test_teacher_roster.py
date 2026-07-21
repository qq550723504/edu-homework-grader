from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import (
    AuditLog,
    ClassTeacher,
    Classroom,
    Enrollment,
    GuardianConsentStatus,
    Role,
    StudentGuardianConsent,
    Tenant,
    User,
    utc_now,
)
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identity


@dataclass
class TeacherContext:
    client: TestClient
    teacher_id: UUID


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def teacher_context(session: Session, monkeypatch: pytest.MonkeyPatch) -> TeacherContext:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    session.add_all([tenant, teacher])
    session.commit()
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject="teacher-subject", school_id=None)
    )
    with TestClient(app) as client:
        yield TeacherContext(client=client, teacher_id=teacher.id)
    app.dependency_overrides.clear()


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer teacher-token"}


def create_owned_class(session: Session, teacher_id: UUID, code: str = "7A") -> Classroom:
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "pilot"))
    assert tenant is not None
    classroom = Classroom(tenant=tenant, code=code, name=f"Year {code[0]} {code[1:]}")
    session.add(classroom)
    session.flush()
    session.add(ClassTeacher(class_id=classroom.id, teacher_id=teacher_id))
    session.commit()
    return classroom


def test_teacher_creates_class_and_is_assigned(
    teacher_context: TeacherContext, session: Session
) -> None:
    response = teacher_context.client.post(
        "/v1/teacher/classes",
        json={"code": "7A", "name": "Year 7 A"},
        headers=auth_headers(),
    )

    assert response.status_code == 201
    class_id = UUID(response.json()["id"])
    assert session.get(ClassTeacher, (class_id, teacher_context.teacher_id)) is not None
    assert session.scalar(select(func.count(AuditLog.id))) == 2


def test_teacher_gets_a_conflict_for_a_duplicate_class_code(
    teacher_context: TeacherContext,
) -> None:
    payload = {"code": "7A", "name": "Year 7 A"}
    assert (
        teacher_context.client.post(
            "/v1/teacher/classes", json=payload, headers=auth_headers()
        ).status_code
        == 201
    )

    response = teacher_context.client.post(
        "/v1/teacher/classes", json=payload, headers=auth_headers()
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "class code already exists"}


def test_teacher_adds_student_to_owned_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)

    response = teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students",
        json={
            "school_id": "S-001",
            "display_name": "Ada",
            "under_14": False,
            "guardian_consent_status": "not_required",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 201
    student = session.scalar(select(User).where(User.school_id == "S-001"))
    assert student is not None
    assert session.get(Enrollment, (classroom.id, student.id)) is not None
    consent = session.get(StudentGuardianConsent, student.id)
    assert consent is not None
    assert consent.status is GuardianConsentStatus.NOT_REQUIRED


def test_teacher_lists_students_in_owned_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)
    for school_id, display_name in (("S-001", "Ada"), ("S-002", "Grace")):
        response = teacher_context.client.post(
            f"/v1/teacher/classes/{classroom.id}/students",
            json={
                "school_id": school_id,
                "display_name": display_name,
                "under_14": False,
                "guardian_consent_status": "not_required",
            },
            headers=auth_headers(),
        )
        assert response.status_code == 201

    response = teacher_context.client.get(
        f"/v1/teacher/classes/{classroom.id}/students", headers=auth_headers()
    )

    students = list(
        session.scalars(
            select(User).where(User.school_id.in_(["S-001", "S-002"])).order_by(User.school_id)
        )
    )
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": str(student.id),
                "school_id": student.school_id,
                "display_name": student.display_name,
            }
            for student in students
        ]
    }


def test_teacher_updates_a_student_display_name_in_owned_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)
    teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students",
        json={
            "school_id": "S-001",
            "display_name": "Ada",
            "under_14": False,
            "guardian_consent_status": "not_required",
        },
        headers=auth_headers(),
    )
    student = session.scalar(select(User).where(User.school_id == "S-001"))
    assert student is not None

    response = teacher_context.client.patch(
        f"/v1/teacher/classes/{classroom.id}/students/{student.id}",
        json={"display_name": "Ada Lovelace"},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": str(student.id),
        "school_id": "S-001",
        "display_name": "Ada Lovelace",
    }
    session.refresh(student)
    assert student.display_name == "Ada Lovelace"
    assert (
        session.scalar(select(AuditLog).where(AuditLog.event_type == "roster.student_name_updated"))
        is not None
    )


def test_teacher_removes_a_student_from_an_owned_class_without_deleting_the_account(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)
    teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students",
        json={
            "school_id": "S-001",
            "display_name": "Ada",
            "under_14": False,
            "guardian_consent_status": "not_required",
        },
        headers=auth_headers(),
    )
    student = session.scalar(select(User).where(User.school_id == "S-001"))
    assert student is not None

    response = teacher_context.client.delete(
        f"/v1/teacher/classes/{classroom.id}/students/{student.id}",
        headers=auth_headers(),
    )

    assert response.status_code == 204
    assert session.get(Enrollment, (classroom.id, student.id)) is None
    assert session.get(User, student.id) is not None
    assert (
        session.scalar(select(AuditLog).where(AuditLog.event_type == "roster.student_removed"))
        is not None
    )


def test_teacher_imports_csv_for_owned_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name,"
        "student_under_14,guardian_consent_status,guardian_consent_notice_version,"
        "guardian_consent_evidence_reference\n"
        "7A,Year 7 A,S-002,Grace,false,not_required,,\n"
    )

    response = teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students/import",
        files={"file": ("roster.csv", csv_body, "text/csv")},
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"imported": 1}
    assert session.scalar(select(func.count(Enrollment.class_id))) == 1


def test_teacher_rejects_csv_for_a_different_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    classroom = create_owned_class(session, teacher_context.teacher_id)
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name,"
        "student_under_14,guardian_consent_status,guardian_consent_notice_version,"
        "guardian_consent_evidence_reference\n"
        "7B,Year 7 B,S-004,Sam,false,not_required,,\n"
    )

    response = teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students/import",
        files={"file": ("roster.csv", csv_body, "text/csv")},
        headers=auth_headers(),
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "CSV class does not match selected class"}
    assert session.scalar(select(func.count(Enrollment.class_id))) == 0


def test_teacher_cannot_write_another_teachers_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "pilot"))
    assert tenant is not None
    other_teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Other")
    session.add(other_teacher)
    session.flush()
    classroom = create_owned_class(session, teacher_context.teacher_id, code="7B")
    class_id = classroom.id
    session.delete(session.get(ClassTeacher, (class_id, teacher_context.teacher_id)))
    session.add(ClassTeacher(class_id=class_id, teacher_id=other_teacher.id))
    session.commit()

    response = teacher_context.client.post(
        f"/v1/teacher/classes/{class_id}/students",
        json={
            "school_id": "S-003",
            "display_name": "Lin",
            "under_14": False,
            "guardian_consent_status": "not_required",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 404
    assert session.scalar(select(func.count(Enrollment.class_id))) == 0


def test_teacher_cannot_overwrite_a_student_from_another_class(
    teacher_context: TeacherContext, session: Session
) -> None:
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "pilot"))
    assert tenant is not None
    other_teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Other")
    other_class = Classroom(tenant=tenant, code="7B", name="Year 7 B")
    student = User(
        tenant=tenant,
        role=Role.STUDENT,
        school_id="S-900",
        display_name="Original name",
    )
    session.add_all([other_teacher, other_class, student])
    session.flush()
    session.add_all(
        [
            ClassTeacher(class_id=other_class.id, teacher_id=other_teacher.id),
            Enrollment(class_id=other_class.id, student_id=student.id),
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=True,
                status=GuardianConsentStatus.GRANTED,
                notice_version="2026-07",
                evidence_reference="school-consent-0001",
                verified_by_user_id=other_teacher.id,
                granted_at=utc_now(),
            ),
        ]
    )
    session.commit()
    classroom = create_owned_class(session, teacher_context.teacher_id)

    response = teacher_context.client.post(
        f"/v1/teacher/classes/{classroom.id}/students",
        json={
            "school_id": "S-900",
            "display_name": "Overwritten name",
            "under_14": False,
            "guardian_consent_status": "not_required",
        },
        headers=auth_headers(),
    )

    assert response.status_code == 422
    session.refresh(student)
    assert student.display_name == "Original name"
    assert session.get(Enrollment, (classroom.id, student.id)) is None
    consent = session.get(StudentGuardianConsent, student.id)
    assert consent is not None
    assert consent.status is GuardianConsentStatus.GRANTED
