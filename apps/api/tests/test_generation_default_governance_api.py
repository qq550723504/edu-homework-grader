from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import Role, Tenant, User
from edu_grader_api.settings import settings


ISSUER = "https://issuer.example.test"


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
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def admin(session: Session, subject: str) -> User:
    tenant = Tenant(slug="pilot", name="Tenant")
    user = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject=subject,
        display_name=subject,
        work_email=f"{subject}@example.test",
    )
    session.add(user)
    session.commit()
    return user


def headers(client: TestClient, user: User) -> dict[str, str]:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject=user.oidc_subject or "", school_id=None)
    )
    return {"Authorization": "Bearer test-token", "Idempotency-Key": "request-1"}


def test_platform_governance_admin_can_read_default_summary(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = admin(session, "platform-admin")
    monkeypatch.setattr(settings, "generation_governance_admin_subjects", "platform-admin")

    response = client.get("/v1/admin/ai-generation-defaults", headers=headers(client, user))

    assert response.status_code == 200
    assert response.json() == {"current": None, "pending": [], "history": []}


def test_tenant_admin_cannot_read_default_summary(client: TestClient, session: Session) -> None:
    response = client.get(
        "/v1/admin/ai-generation-defaults", headers=headers(client, admin(session, "tenant-admin"))
    )

    assert response.status_code == 404


def test_platform_governance_admin_submits_redacted_default_change(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = admin(session, "platform-admin")
    monkeypatch.setattr(settings, "generation_governance_admin_subjects", "platform-admin")
    report = {
        "spec_id": "governance-v1",
        "exporter_version": "export-v1",
        "run_id": "run-1",
        "tenant_id": "pilot",
        "watermark": datetime(2026, 7, 28, tzinfo=timezone.utc).isoformat(),
        "baseline": {
            "provider_name": "fake",
            "model_id": "fake-v0",
            "prompt_version": "generator-v1",
            "validator_version": "verification-v1",
        },
        "candidate": {
            "provider_name": "fake",
            "model_id": "fake-v1",
            "prompt_version": "generator-v1",
            "validator_version": "verification-v1",
        },
        "promotion_eligible": True,
        "export_manifest": {
            "exporter_version": "export-v1",
            "run_id": "run-1",
            "tenant_id": "pilot",
            "watermark": datetime(2026, 7, 28, tzinfo=timezone.utc).isoformat(),
            "record_count": 1,
            "issue_count": 0,
            "record_digest": "a" * 64,
            "source_counts": {"accepted_directly": 1},
        },
    }

    response = client.post(
        "/v1/admin/ai-generation-default-change-requests",
        headers=headers(client, user),
        json={
            "provider_name": "fake",
            "model_version": "fake-v1",
            "prompt_version": "generator-v1",
            "request_reason": "Verified promotion",
            "evaluation_report": report,
        },
    )

    assert response.status_code == 201
    assert response.json()["status"] == "pending_approval"
    assert "evaluation_report" not in response.json()
