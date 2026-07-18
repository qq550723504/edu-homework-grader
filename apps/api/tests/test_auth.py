from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import Role, Tenant, User
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        assert token == "test-token"
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


def set_identity(client: TestClient, identity: VerifiedIdentity) -> None:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(identity)


@pytest.mark.parametrize(
    "identity",
    [
        VerifiedIdentity(
            issuer="https://wrong-issuer.example.test", subject="s-1", school_id="S-001"
        ),
        VerifiedIdentity(issuer=ISSUER, subject="", school_id="S-001"),
    ],
)
def test_invalid_verified_identity_returns_401(
    client: TestClient, identity: VerifiedIdentity
) -> None:
    set_identity(client, identity)

    response = client.get("/v1/me", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 401


def test_first_student_login_binds_rostered_identity_to_configured_tenant(
    client: TestClient, session: Session
) -> None:
    pilot = Tenant(slug="pilot", name="Pilot")
    other = Tenant(slug="other", name="Other")
    pilot_student = User(
        tenant=pilot,
        role=Role.STUDENT,
        school_id="S-001",
        display_name="Pilot student",
    )
    other_student = User(
        tenant=other,
        role=Role.STUDENT,
        school_id="S-001",
        display_name="Other student",
    )
    session.add_all([pilot, other, pilot_student, other_student])
    session.commit()
    set_identity(client, VerifiedIdentity(issuer=ISSUER, subject="subject-1", school_id="S-001"))

    response = client.get("/v1/me", headers={"Authorization": "Bearer test-token"})

    assert response.status_code == 200
    assert response.json() == {
        "id": str(pilot_student.id),
        "tenant_id": str(pilot.id),
        "role": "student",
        "school_id": "S-001",
        "display_name": "Pilot student",
    }
    session.refresh(pilot_student)
    session.refresh(other_student)
    assert pilot_student.oidc_subject == "subject-1"
    assert other_student.oidc_subject is None
