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
    Enrollment,
    GuardianConsentStatus,
    Role,
    StudentGuardianConsent,
    Tenant,
    User,
)
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
def admin_client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    tenant = Tenant(slug="pilot", name="Pilot")
    admin = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="admin-subject",
        display_name="Administrator",
    )
    session.add_all([tenant, admin])
    session.commit()
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject="admin-subject", school_id=None)
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_invalid_csv_rolls_back_every_row(admin_client: TestClient, session: Session) -> None:
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name\n"
        "7A,Year 7 A,S-001,Ada\n"
        "7A,Year 7 A,S-001,Duplicate\n"
    )

    response = admin_client.post(
        "/v1/admin/students/import",
        files={"file": ("roster.csv", csv_body, "text/csv")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 422
    assert session.scalar(select(func.count(User.id))) == 1


def test_reimport_updates_name_without_duplicate_enrollment(
    admin_client: TestClient, session: Session
) -> None:
    header = (
        "class_code,class_name,student_school_id,student_display_name,"
        "student_under_14,guardian_consent_status,guardian_consent_notice_version,"
        "guardian_consent_evidence_reference\n"
    )
    first = header + "7A,Year 7 A,S-001,Ada,false,not_required,,\n"
    second = header + "7A,Year 7 A,S-001,Ada Lovelace,false,not_required,,\n"

    assert (
        admin_client.post(
            "/v1/admin/students/import",
            files={"file": ("r.csv", first, "text/csv")},
            headers={"Authorization": "Bearer test-token"},
        ).status_code
        == 200
    )
    assert (
        admin_client.post(
            "/v1/admin/students/import",
            files={"file": ("r.csv", second, "text/csv")},
            headers={"Authorization": "Bearer test-token"},
        ).status_code
        == 200
    )
    assert session.scalar(select(func.count(Enrollment.class_id))) == 1


def test_roster_import_records_school_verified_guardian_consent(
    admin_client: TestClient, session: Session
) -> None:
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name,"
        "student_under_14,guardian_consent_status,guardian_consent_notice_version,"
        "guardian_consent_evidence_reference\n"
        "7A,Year 7 A,S-001,Ada,true,granted,2026-07,school-consent-0001\n"
    )

    response = admin_client.post(
        "/v1/admin/students/import",
        files={"file": ("roster.csv", csv_body, "text/csv")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    student = session.scalar(select(User).where(User.school_id == "S-001"))
    assert student is not None
    consent = session.get(StudentGuardianConsent, student.id)
    assert consent is not None
    assert consent.requires_guardian_consent is True
    assert consent.status == GuardianConsentStatus.GRANTED
    assert consent.notice_version == "2026-07"
    assert consent.evidence_reference == "school-consent-0001"


def test_invalid_under_fourteen_consent_rolls_back_import(
    admin_client: TestClient, session: Session
) -> None:
    csv_body = (
        "class_code,class_name,student_school_id,student_display_name,"
        "student_under_14,guardian_consent_status,guardian_consent_notice_version,"
        "guardian_consent_evidence_reference\n"
        "7A,Year 7 A,S-001,Ada,true,not_required,,\n"
    )

    response = admin_client.post(
        "/v1/admin/students/import",
        files={"file": ("roster.csv", csv_body, "text/csv")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 422
    assert session.scalar(select(func.count(User.id))) == 1


def test_admin_can_create_class_and_assign_tenant_teacher(
    admin_client: TestClient, session: Session
) -> None:
    teacher = User(
        tenant=session.scalar(select(Tenant).where(Tenant.slug == "pilot")),
        role=Role.TEACHER,
        display_name="Teacher",
    )
    session.add(teacher)
    session.commit()

    created = admin_client.post(
        "/v1/admin/classes",
        json={"code": "7A", "name": "Year 7 A"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert created.status_code == 201
    class_id = created.json()["id"]
    assigned = admin_client.put(
        f"/v1/admin/classes/{class_id}/teachers/{teacher.id}",
        headers={"Authorization": "Bearer test-token"},
    )

    assert assigned.status_code == 200
    assert session.get(ClassTeacher, (UUID(class_id), teacher.id)) is not None
    assert session.scalar(select(func.count(AuditLog.id))) == 2
