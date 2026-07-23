from dataclasses import dataclass
from uuid import UUID

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
    GenerationControlState,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.generation_governance import (
    GenerationGovernanceError,
    assert_generation_pipeline_allowed,
)
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identity


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine) -> Session:
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    monkeypatch.setattr(settings, "generation_governance_admin_subjects", "")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_admin(session: Session, *, subject: str = "tenant-admin") -> User:
    tenant = Tenant(slug="pilot", name="Pilot")
    admin = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject=subject,
        display_name="Admin",
        work_email="admin@example.test",
    )
    session.add(admin)
    session.commit()
    return admin


def authorize(client: TestClient, user: User) -> dict[str, str]:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject=user.oidc_subject or "", school_id=None)
    )
    return {"Authorization": "Bearer test-token"}


def add_entry(
    session: Session,
    *,
    tenant_id: UUID | None,
    is_global: bool,
    state: GenerationControlState,
    target_type: GenerationGovernanceTargetType = GenerationGovernanceTargetType.PROMPT_VERSION,
    target_key: str = "generator-v2",
) -> None:
    session.add(
        GenerationGovernanceEntry(
            tenant_id=None if is_global else tenant_id,
            is_global=is_global,
            target_type=target_type,
            target_key=target_key,
            control_state=state,
        )
    )
    session.flush()


@pytest.mark.parametrize(
    "global_state,tenant_state",
    [
        (GenerationControlState.PAUSED, GenerationControlState.ACTIVE),
        (GenerationControlState.PAUSED, GenerationControlState.CANARY),
        (GenerationControlState.RETIRED, GenerationControlState.ACTIVE),
        (GenerationControlState.RETIRED, GenerationControlState.CANARY),
    ],
)
def test_global_kill_switch_cannot_be_overridden(
    session: Session,
    global_state: GenerationControlState,
    tenant_state: GenerationControlState,
) -> None:
    admin = create_admin(session)
    add_entry(session, tenant_id=admin.tenant_id, is_global=True, state=global_state)
    add_entry(session, tenant_id=admin.tenant_id, is_global=False, state=tenant_state)

    with pytest.raises(GenerationGovernanceError, match="prompt_version_control_blocked"):
        assert_generation_pipeline_allowed(
            session,
            tenant_id=admin.tenant_id,
            curriculum_profile_id="profile-1",
            prompt_version="generator-v2",
            provider_name="fake",
            model_version="fake-v1",
        )


def test_global_canary_requires_explicit_tenant_canary(session: Session) -> None:
    admin = create_admin(session)
    add_entry(
        session,
        tenant_id=admin.tenant_id,
        is_global=True,
        state=GenerationControlState.CANARY,
    )

    with pytest.raises(GenerationGovernanceError, match="prompt_version_control_blocked"):
        assert_generation_pipeline_allowed(
            session,
            tenant_id=admin.tenant_id,
            curriculum_profile_id="profile-1",
            prompt_version="generator-v2",
            provider_name="fake",
            model_version="fake-v1",
        )

    add_entry(
        session,
        tenant_id=admin.tenant_id,
        is_global=False,
        state=GenerationControlState.CANARY,
    )
    assert_generation_pipeline_allowed(
        session,
        tenant_id=admin.tenant_id,
        curriculum_profile_id="profile-1",
        prompt_version="generator-v2",
        provider_name="fake",
        model_version="fake-v1",
    )


def test_tenant_admin_write_is_committed_and_audited(
    client: TestClient, session: Session, engine
) -> None:
    admin = create_admin(session)
    response = client.post(
        "/v1/admin/ai-generation-governance",
        headers=authorize(client, admin),
        json={
            "is_global": False,
            "target_type": "prompt_version",
            "target_key": "generator-v2",
            "control_state": "paused",
            "note": "Tenant maintenance window",
        },
    )

    assert response.status_code == 201
    entry_id = UUID(response.json()["id"])
    with Session(engine) as verification_session:
        entry = verification_session.get(GenerationGovernanceEntry, entry_id)
        assert entry is not None
        assert entry.tenant_id == admin.tenant_id
        assert entry.control_state is GenerationControlState.PAUSED
        audit = verification_session.scalar(
            select(AuditLog).where(
                AuditLog.event_type == "ai_generation_governance.entry_created",
                AuditLog.target_id == entry_id,
            )
        )
        assert audit is not None


def test_tenant_admin_cannot_create_or_transition_global_control(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin = create_admin(session)
    headers = authorize(client, admin)

    response = client.post(
        "/v1/admin/ai-generation-governance",
        headers=headers,
        json={
            "is_global": True,
            "target_type": "generator",
            "target_key": "generator",
            "control_state": "paused",
        },
    )
    assert response.status_code == 404

    monkeypatch.setattr(settings, "generation_governance_admin_subjects", admin.oidc_subject or "")
    created = client.post(
        "/v1/admin/ai-generation-governance",
        headers=headers,
        json={
            "is_global": True,
            "target_type": "generator",
            "target_key": "generator",
            "control_state": "active",
        },
    )
    assert created.status_code == 201
    monkeypatch.setattr(settings, "generation_governance_admin_subjects", "")

    transitioned = client.post(
        f"/v1/admin/ai-generation-governance/{created.json()['id']}/transition",
        headers=headers,
        json={"control_state": "paused"},
    )
    assert transitioned.status_code == 404


def test_platform_governance_admin_can_commit_global_transition(
    client: TestClient,
    session: Session,
    engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = create_admin(session, subject="platform-governance-admin")
    monkeypatch.setattr(
        settings,
        "generation_governance_admin_subjects",
        "platform-governance-admin",
    )
    headers = authorize(client, admin)

    created = client.post(
        "/v1/admin/ai-generation-governance",
        headers=headers,
        json={
            "is_global": True,
            "target_type": "provider",
            "target_key": "openai",
            "control_state": "active",
        },
    )
    assert created.status_code == 201
    entry_id = UUID(created.json()["id"])

    transitioned = client.post(
        f"/v1/admin/ai-generation-governance/{entry_id}/transition",
        headers=headers,
        json={"control_state": "paused"},
    )
    assert transitioned.status_code == 200

    with Session(engine) as verification_session:
        entry = verification_session.get(GenerationGovernanceEntry, entry_id)
        assert entry is not None
        assert entry.is_global is True
        assert entry.tenant_id is None
        assert entry.control_state is GenerationControlState.PAUSED
        events = verification_session.scalars(
            select(AuditLog).where(AuditLog.target_id == entry_id).order_by(AuditLog.sequence)
        ).all()
        assert [event.event_type for event in events] == [
            "ai_generation_governance.entry_created",
            "ai_generation_governance.entry_transitioned",
        ]
