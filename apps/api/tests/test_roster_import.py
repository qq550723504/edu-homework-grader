from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import Enrollment, Role, Tenant, User
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
    first = "class_code,class_name,student_school_id,student_display_name\n7A,Year 7 A,S-001,Ada\n"
    second = "class_code,class_name,student_school_id,student_display_name\n7A,Year 7 A,S-001,Ada Lovelace\n"

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
