from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.e2e_support import DeterministicM2Client
from edu_grader_api.main import app
from edu_grader_api.models import (
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    GenerationJob,
    QuestionVersion,
    Role,
    Tenant,
    User,
)
from edu_grader_api.settings import settings
import edu_grader_api.routers.ai_question_validation as validation_router
from edu_generator.prompt_templates import resolve_prompt_template


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


def teacher_and_objective(session: Session) -> tuple[User, CurriculumObjectiveRevision]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    profile = CurriculumProfile(
        code="pilot-math-2026",
        name="Pilot Mathematics",
        jurisdiction="pilot",
        version_label="2026",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=CurriculumSourceRecord(
            issuer="Example Board",
            title="Math curriculum",
            canonical_url="https://curriculum.example.test/math",
            version_label="2026",
        ),
    )
    grade = CurriculumGradeMapping(
        profile=profile,
        internal_level="G5",
        external_label="Grade 5",
        position=5,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code="MATH-G5-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Use whole numbers under 100.",
        source_locator="section 1",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add_all([teacher, revision])
    session.commit()
    return teacher, revision


def teacher_and_e4_objective(session: Session) -> tuple[User, CurriculumObjectiveRevision]:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E4"]
    session.commit()
    return teacher, revision


def create_and_fetch_e4_draft(client: TestClient, session: Session) -> object:
    teacher, revision = teacher_and_e4_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "e4-reading-material"}
    created = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "grade": "Grade 5",
            "subject": "mathematics",
            "question_types": ["E4"],
            "requested_count": 1,
            "policy_catalog_version": "2026.07",
            "prompt_version": "generator-v1",
        },
    )
    assert created.status_code == 201
    return client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    )


def test_teacher_job_request_is_idempotent_and_never_publishes(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "same-request"}
    payload = {
        "curriculum_objective_revision_id": str(revision.id),
        "grade": "Grade 5",
        "subject": "mathematics",
        "question_types": ["M1"],
        "requested_count": 1,
        "policy_catalog_version": "2026.07",
        "prompt_version": "generator-v1",
    }

    first = client.post("/v1/ai-question-generation/jobs", json=payload, headers=headers)
    second = client.post("/v1/ai-question-generation/jobs", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    questions = client.get(
        f"/v1/ai-question-generation/jobs/{first.json()['id']}/questions", headers=headers
    )
    assert questions.status_code == 200
    assert questions.json()["items"][0]["teacher_state"] == "pending_review"
    assert session.scalars(select(QuestionVersion)).all() == []


def test_generation_job_and_draft_payloads_do_not_expose_system_prompt(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "prompt-not-exposed"}
    teacher_constraint = "teacher-constraint-secret"
    created = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "grade": "Grade 5",
            "subject": "mathematics",
            "question_types": ["M1"],
            "requested_count": 1,
            "policy_catalog_version": "2026.07",
            "prompt_version": "generator-v1",
            "teacher_constraint": teacher_constraint,
        },
    )
    job = client.get(f"/v1/ai-question-generation/jobs/{created.json()['id']}", headers=headers)
    drafts = client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    )
    system_instructions = resolve_prompt_template("generator-v1", ["M1"]).system_instructions

    assert created.status_code == 201
    assert job.status_code == 200
    assert drafts.status_code == 200
    assert system_instructions not in str(created.json())
    assert system_instructions not in str(job.json())
    assert system_instructions not in str(drafts.json())
    assert teacher_constraint not in str(created.json())
    assert teacher_constraint not in str(job.json())
    assert teacher_constraint not in str(drafts.json())
    persisted_job = session.scalar(
        select(GenerationJob).where(GenerationJob.id == UUID(created.json()["id"]))
    )
    assert persisted_job is not None
    assert teacher_constraint not in str(persisted_job.attempts[0].request_summary)


def test_teacher_question_list_returns_e4_reading_material(
    client: TestClient, session: Session
) -> None:
    response = create_and_fetch_e4_draft(client, session)

    assert response.status_code == 200
    assert response.json()["items"][0]["candidate"]["reading_material"]


def test_generation_job_rejects_a_batch_over_the_configured_limit(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, revision = teacher_and_objective(session)
    monkeypatch.setattr(settings, "generator_max_batch_size", 1)

    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers=authorize(client, teacher) | {"Idempotency-Key": "oversized-request"},
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "grade": "Grade 5",
            "subject": "mathematics",
            "question_types": ["M1"],
            "requested_count": 2,
            "policy_catalog_version": "2026.07",
            "prompt_version": "generator-v1",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_batch_limit_exceeded"


def test_teacher_can_create_and_read_immutable_validation_runs(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "validation-run"}
    created = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "grade": "Grade 5",
            "subject": "mathematics",
            "question_types": ["M1"],
            "requested_count": 1,
            "policy_catalog_version": "2026.07",
            "prompt_version": "generator-v1",
        },
    )
    draft_id = client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    ).json()["items"][0]["id"]
    monkeypatch.setattr(validation_router, "HttpGraderClient", DeterministicM2Client)

    created_run = client.post(
        f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers
    )
    history = client.get(f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers)
    fetched = client.get(
        f"/v1/ai-question-validation-runs/{created_run.json()['id']}", headers=headers
    )

    assert created_run.status_code == 201
    assert created_run.json()["status"] == "passed"
    assert history.json()["items"][0]["id"] == created_run.json()["id"]
    assert fetched.json()["findings"] == []
