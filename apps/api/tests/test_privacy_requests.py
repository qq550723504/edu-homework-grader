from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import (
    AuditLog,
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


def student_and_admin(session: Session) -> tuple[User, User]:
    tenant = Tenant(slug="pilot", name="Pilot")
    admin = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="admin",
        display_name="Administrator",
    )
    student = User(
        tenant=tenant,
        role=Role.STUDENT,
        school_id="S-001",
        oidc_issuer=ISSUER,
        oidc_subject="student",
        display_name="Student",
    )
    session.add_all([tenant, admin, student])
    session.flush()
    session.add(
        StudentGuardianConsent(
            student_id=student.id,
            requires_guardian_consent=False,
            status=GuardianConsentStatus.NOT_REQUIRED,
        )
    )
    session.commit()
    return admin, student


def test_request_immediately_blocks_every_student_processing_route(
    client: TestClient, session: Session
) -> None:
    admin, student = student_and_admin(session)
    created = client.post(
        f"/v1/admin/students/{student.id}/privacy-requests",
        headers=authorize(client, admin),
        json={"reason": "school verified request"},
    )

    assert created.status_code == 201
    student_headers = authorize(client, student)
    request_id = uuid4()
    endpoints = [
        ("get", "/v1/student/assignments", {}),
        ("get", f"/v1/student/assignments/{request_id}", {}),
        (
            "put",
            f"/v1/student/attempts/{request_id}/answers/{uuid4()}",
            {"json": {"answer": {"value": "5"}, "version": 0}},
        ),
        (
            "post",
            f"/v1/student/assignments/{request_id}/submit",
            {"headers": {"Idempotency-Key": str(uuid4())}},
        ),
        (
            "post",
            f"/v1/student/attempts/{request_id}/submit",
            {"headers": {"Idempotency-Key": str(uuid4())}},
        ),
        ("post", f"/v1/student/attempts/{request_id}/appeals", {"json": {"reason": "Review"}}),
        ("get", "/v1/student/appeals", {}),
    ]

    for method, path, options in endpoints:
        request_headers = student_headers | options.pop("headers", {})
        response = getattr(client, method)(path, headers=request_headers, **options)
        assert response.status_code == 403
        assert response.json() == {"detail": "data processing restricted"}


def test_hold_blocks_approval_and_rejection_releases_processing(
    client: TestClient, session: Session
) -> None:
    admin, student = student_and_admin(session)
    headers = authorize(client, admin)
    created = client.post(
        f"/v1/admin/students/{student.id}/privacy-requests",
        headers=headers,
        json={"reason": "school verified request"},
    )
    request_id = created.json()["id"]
    held = client.post(
        f"/v1/admin/privacy-requests/{request_id}/hold",
        headers=headers,
        json={"reason": "security incident", "version": 0},
    )

    assert held.status_code == 200
    approval = client.post(
        f"/v1/admin/privacy-requests/{request_id}/approve",
        headers=headers,
        json={"eligible_for_deletion_at": "2026-07-20T00:00:00+00:00", "version": 1},
    )
    assert approval.status_code == 422
    rejected = client.post(
        f"/v1/admin/privacy-requests/{request_id}/reject",
        headers=headers,
        json={"reason": "request withdrawn", "version": 1},
    )

    assert rejected.status_code == 200
    assert rejected.json() == {"status": "rejected", "version": 2}
    assert (
        client.get("/v1/student/assignments", headers=authorize(client, student)).status_code == 200
    )
    assert session.scalars(select(AuditLog.event_type).order_by(AuditLog.sequence)).all() == [
        "privacy_request.created",
        "privacy_request.held",
        "privacy_request.rejected",
    ]
