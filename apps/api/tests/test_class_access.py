from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import AuditLog, ClassTeacher, Classroom, Enrollment, Role, Tenant, User
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identity


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
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def authorize(client: TestClient, user: User) -> dict[str, str]:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject=user.oidc_subject or "", school_id=user.school_id)
    )
    return {"Authorization": "Bearer test-token"}


def test_class_visibility_is_limited_to_membership(client: TestClient, session: Session) -> None:
    pilot = Tenant(slug="pilot", name="Pilot")
    other = Tenant(slug="other", name="Other")
    classroom = Classroom(tenant=pilot, code="7A", name="Year 7 A")
    teacher = User(
        tenant=pilot,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    unassigned = User(
        tenant=pilot,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="unassigned",
        display_name="Unassigned",
    )
    student = User(
        tenant=pilot,
        role=Role.STUDENT,
        school_id="S-001",
        oidc_issuer=ISSUER,
        oidc_subject="student",
        display_name="Student",
    )
    other_admin = User(
        tenant=other,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="other-admin",
        display_name="Other admin",
    )
    session.add_all([pilot, other, classroom, teacher, unassigned, student, other_admin])
    session.flush()
    session.add_all(
        [
            ClassTeacher(class_id=classroom.id, teacher_id=teacher.id),
            Enrollment(class_id=classroom.id, student_id=student.id),
        ]
    )
    session.commit()

    assert (
        client.get(f"/v1/classes/{classroom.id}", headers=authorize(client, teacher)).status_code
        == 200
    )
    assert (
        client.get(f"/v1/classes/{classroom.id}", headers=authorize(client, student)).status_code
        == 200
    )
    assert (
        client.get(f"/v1/classes/{classroom.id}", headers=authorize(client, unassigned)).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/classes/{classroom.id}", headers=authorize(client, other_admin)
        ).status_code
        == 404
    )


def test_teacher_lists_only_their_own_classes(client: TestClient, session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    assigned = Classroom(tenant=tenant, code="7A", name="Year 7 A")
    unassigned = Classroom(tenant=tenant, code="7B", name="Year 7 B")
    session.add_all([tenant, teacher, assigned, unassigned])
    session.flush()
    session.add(ClassTeacher(class_id=assigned.id, teacher_id=teacher.id))
    session.commit()

    response = client.get("/v1/classes", headers=authorize(client, teacher))

    assert response.status_code == 200
    assert response.json() == {
        "classes": [{"id": str(assigned.id), "code": "7A", "name": "Year 7 A"}]
    }


def test_audit_logs_are_scoped_to_the_current_tenant(client: TestClient, session: Session) -> None:
    pilot = Tenant(slug="pilot", name="Pilot")
    other = Tenant(slug="other", name="Other")
    admin = User(
        tenant=pilot,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="admin",
        display_name="Admin",
    )
    session.add_all([pilot, other, admin])
    session.flush()
    session.add_all(
        [
            AuditLog(
                tenant_id=pilot.id,
                actor_user_id=admin.id,
                event_type="pilot.event",
                target_type="test",
                target_id=uuid4(),
                metadata_json={},
            ),
            AuditLog(
                tenant_id=other.id,
                actor_user_id=None,
                event_type="other.event",
                target_type="test",
                target_id=uuid4(),
                metadata_json={},
            ),
        ]
    )
    session.commit()

    response = client.get("/v1/admin/audit-logs", headers=authorize(client, admin))

    assert response.status_code == 200
    assert [entry["event_type"] for entry in response.json()["items"]] == ["pilot.event"]
