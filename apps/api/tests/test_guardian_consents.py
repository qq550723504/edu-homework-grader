from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import CurrentPrincipal, VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.dependencies import require_student_consent
from edu_grader_api.main import app
from edu_grader_api.models import (
    AuditLog,
    GuardianConsentStatus,
    Role,
    StudentGuardianConsent,
    Tenant,
    User,
)
from edu_grader_api.services.guardian_consents import (
    GuardianConsentConflictError,
    grant_guardian_consent,
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
            requires_guardian_consent=True,
            status=GuardianConsentStatus.PENDING,
        )
    )
    session.commit()
    return admin, student


def test_pending_guardian_consent_blocks_student_assignment_access(
    client: TestClient, session: Session
) -> None:
    _, student = student_and_admin(session)

    headers = authorize(client, student)
    student_id = uuid4()
    endpoints = [
        ("get", "/v1/student/assignments", {}),
        ("get", f"/v1/student/assignments/{student_id}", {}),
        (
            "put",
            f"/v1/student/attempts/{student_id}/answers/{uuid4()}",
            {"json": {"answer": {"value": "5"}, "version": 0}},
        ),
        (
            "post",
            f"/v1/student/assignments/{student_id}/submit",
            {"headers": {"Idempotency-Key": str(uuid4())}},
        ),
        (
            "post",
            f"/v1/student/attempts/{student_id}/submit",
            {"headers": {"Idempotency-Key": str(uuid4())}},
        ),
        ("post", f"/v1/student/attempts/{student_id}/appeals", {"json": {"reason": "Review"}}),
        ("get", "/v1/student/appeals", {}),
    ]

    for method, path, options in endpoints:
        request_headers = headers | options.pop("headers", {})
        response = getattr(client, method)(path, headers=request_headers, **options)
        assert response.status_code == 403
        assert response.json() == {"detail": "guardian consent required"}


def test_missing_guardian_consent_blocks_student_assignment_access(
    client: TestClient, session: Session
) -> None:
    _, student = student_and_admin(session)
    consent = session.get(StudentGuardianConsent, student.id)
    assert consent is not None
    session.delete(consent)
    session.commit()

    response = client.get("/v1/student/assignments", headers=authorize(client, student))

    assert response.status_code == 403
    assert response.json() == {"detail": "guardian consent required"}


def test_contradictory_not_required_consent_is_fail_closed_at_runtime() -> None:
    consent = StudentGuardianConsent(
        student_id=uuid4(),
        requires_guardian_consent=True,
        status=GuardianConsentStatus.NOT_REQUIRED,
    )

    class LegacyConsentSession:
        def get(
            self, model: type[StudentGuardianConsent], student_id: object
        ) -> StudentGuardianConsent:
            assert model is StudentGuardianConsent
            assert student_id == consent.student_id
            return consent

    principal = CurrentPrincipal(
        user_id=str(consent.student_id),
        tenant_id=str(uuid4()),
        role=Role.STUDENT,
        school_id="S-001",
        display_name="Student",
    )

    with pytest.raises(HTTPException) as error:
        require_student_consent(principal, LegacyConsentSession())

    assert error.value.status_code == 403
    assert error.value.detail == "guardian consent required"


def test_admin_can_grant_then_withdraw_guardian_consent(
    client: TestClient, session: Session
) -> None:
    admin, student = student_and_admin(session)

    granted = client.post(
        f"/v1/admin/students/{student.id}/guardian-consent/grant",
        headers=authorize(client, admin),
        json={
            "notice_version": "2026-07",
            "evidence_reference": "school-consent-0001",
            "version": 0,
        },
    )

    assert granted.status_code == 200
    assert granted.json()["status"] == "granted"
    withdrawn = client.post(
        f"/v1/admin/students/{student.id}/guardian-consent/withdraw",
        headers=authorize(client, admin),
        json={"reason": "guardian withdrew consent", "version": 1},
    )

    assert withdrawn.status_code == 200
    consent = session.get(StudentGuardianConsent, student.id)
    assert consent is not None
    assert consent.status == GuardianConsentStatus.WITHDRAWN
    assert consent.withdrawal_reason == "guardian withdrew consent"
    assert session.scalars(select(AuditLog.event_type).order_by(AuditLog.sequence)).all() == [
        "guardian_consent.granted",
        "guardian_consent.withdrawn",
    ]


def test_stale_guardian_consent_update_is_rejected_at_database_write(
    session: Session,
) -> None:
    admin, student = student_and_admin(session)
    concurrent_session = Session(session.get_bind())
    try:
        stale_consent = concurrent_session.get(StudentGuardianConsent, student.id)
        assert stale_consent is not None
        assert stale_consent.version == 0

        grant_guardian_consent(
            session,
            tenant_id=admin.tenant_id,
            actor_user_id=admin.id,
            student_id=student.id,
            notice_version="2026-07",
            evidence_reference="school-consent-0001",
            expected_version=0,
        )
        session.commit()

        with pytest.raises(GuardianConsentConflictError, match="guardian consent changed"):
            grant_guardian_consent(
                concurrent_session,
                tenant_id=admin.tenant_id,
                actor_user_id=admin.id,
                student_id=student.id,
                notice_version="2026-08",
                evidence_reference="school-consent-0002",
                expected_version=0,
            )
    finally:
        concurrent_session.rollback()
        concurrent_session.close()
