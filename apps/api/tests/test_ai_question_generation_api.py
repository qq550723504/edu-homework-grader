from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import (
    CurrentPrincipal,
    VerifiedIdentity,
    get_current_principal,
    get_token_verifier,
)
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
    GenerationJobStatus,
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GeneratedQuestionReviewDecision,
    GenerationValidationRun,
    QuestionVersion,
    Role,
    Tenant,
    User,
    ValidationFinding,
    ValidationFindingSeverity,
    ValidationRunStatus,
)
from edu_grader_api.settings import settings
import edu_grader_api.routers.ai_question_validation as validation_router
import edu_grader_api.routers.ai_question_generation as generation_router
import edu_grader_api.services.question_verification as question_verification
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


def assert_public_validation_payload_is_sanitized(
    payload: object,
    *,
    forbidden_values: tuple[str, ...],
) -> None:
    string_values: list[str] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized_key = str(key).casefold()
                assert "hash" not in normalized_key
                assert "fingerprint" not in normalized_key
                assert "digest" not in normalized_key
                assert not normalized_key.endswith("revision_id")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str):
            string_values.append(value)

    visit(payload)
    for forbidden in forbidden_values:
        assert all(forbidden not in value for value in string_values)


def test_public_validation_feature_summary_uses_recursive_allowlist() -> None:
    summary = validation_router._public_feature_summary(
        {
            "finding_count": 1,
            "content_policy_version": "minor-content-policy-v1",
            "similarity_threshold": 0.9,
            "comparison_counts": {
                "published_question": 2,
                "batch_candidate": 3,
                "future_count": 999,
            },
            "embedding_dependency": {
                "id": "public-model",
                "revision": "public-revision",
                "digest": "private-digest",
                "future_provider_field": "private-by-default",
            },
            "difficulty_signal": {
                "version": "rule-based-difficulty-v1",
                "availability": "available",
                "reason": None,
                "target": 0.6,
                "estimated": 0.5,
                "deviation": 0.1,
                "curriculum_range": {
                    "min": 0.2,
                    "max": 0.8,
                    "future_range_field": "private-by-default",
                },
                "features": [
                    {
                        "type": "prompt_units",
                        "value": 5,
                        "contribution": 0.01,
                        "future_feature_field": "private-by-default",
                        "content_hash": "private-content-hash",
                    }
                ],
                "future_signal_field": "private-by-default",
            },
            "candidate_prompt_fingerprint": {"exact_hash": "private-prompt-hash"},
            "future_unreviewed_field": "private-by-default",
        }
    )

    assert summary == {
        "finding_count": 1,
        "content_policy_version": "minor-content-policy-v1",
        "similarity_threshold": 0.9,
        "comparison_counts": {"published_question": 2, "batch_candidate": 3},
        "embedding_dependency": {
            "id": "public-model",
            "revision": "public-revision",
        },
        "difficulty_signal": {
            "version": "rule-based-difficulty-v1",
            "availability": "available",
            "reason": None,
            "target": 0.6,
            "estimated": 0.5,
            "deviation": 0.1,
            "curriculum_range": {"min": 0.2, "max": 0.8},
            "features": [{"type": "prompt_units", "value": 5, "contribution": 0.01}],
        },
    }


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
            "question_types": ["E4"],
            "requested_count": 1,
        },
    )
    assert created.status_code == 201
    return client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    )


def create_generation_job(
    client: TestClient,
    teacher: User,
    revision: CurriculumObjectiveRevision,
    *,
    idempotency_key: str,
) -> tuple[dict[str, str], dict[str, object]]:
    headers = authorize(client, teacher) | {"Idempotency-Key": idempotency_key}
    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 1,
        },
    )
    assert response.status_code == 201
    return headers, response.json()


def fetch_only_draft(
    client: TestClient, headers: dict[str, str], job_id: object
) -> dict[str, object]:
    response = client.get(
        f"/v1/ai-question-generation/jobs/{job_id}/questions",
        headers=headers,
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    return items[0]


def test_generation_create_derives_course_and_versions_from_active_objective(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)

    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers=authorize(client, teacher) | {"Idempotency-Key": "derived-course-context"},
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 1,
        },
    )

    assert response.status_code == 201
    job = session.get(GenerationJob, UUID(response.json()["id"]))
    assert job is not None
    assert job.grade == revision.objective.grade_mapping.internal_level
    assert job.subject == revision.objective.subject
    assert job.policy_version == "2026.07"
    assert job.prompt_version == "generator-v1"


def test_generation_rejects_type_count_mismatch_with_a_stable_public_error(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)

    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers=authorize(client, teacher) | {"Idempotency-Key": "type-count-mismatch"},
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 2,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_distribution_invalid"


def test_generation_create_rejects_client_owned_course_and_version_fields(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)

    response = client.post(
        "/v1/ai-question-generation/jobs",
        headers=authorize(client, teacher) | {"Idempotency-Key": "client-owned-context"},
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 1,
            "grade": "forged-grade",
            "subject": "forged-subject",
            "policy_catalog_version": "forged-catalog",
            "prompt_version": "forged-prompt",
        },
    )

    assert response.status_code == 422


def test_generation_limits_are_tenant_scoped(client: TestClient, session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    other_tenant = Tenant(slug="other-school", name="Other school")
    other_teacher = User(
        tenant=other_tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="other-tenant-teacher",
        display_name="Other tenant teacher",
        work_email="other-tenant-teacher@example.test",
    )
    session.add(other_teacher)
    session.flush()
    session.add_all(
        [
            GenerationJob(
                tenant_id=teacher.tenant_id,
                teacher_user_id=teacher.id,
                curriculum_objective_revision_id=revision.id,
                requested_count=3,
                status=GenerationJobStatus.QUEUED,
                idempotency_key="limits-current-tenant",
            ),
            GenerationJob(
                tenant_id=other_teacher.tenant_id,
                teacher_user_id=other_teacher.id,
                curriculum_objective_revision_id=revision.id,
                requested_count=5,
                status=GenerationJobStatus.QUEUED,
                idempotency_key="limits-other-tenant",
            ),
        ]
    )
    session.commit()

    response = client.get("/v1/ai-question-generation/limits", headers=authorize(client, teacher))

    assert response.status_code == 200
    assert response.json() == {
        "max_batch_size": settings.generator_max_batch_size,
        "daily_tenant_limit": settings.generator_daily_tenant_limit,
        "daily_used_count": 3,
        "remaining_count": settings.generator_daily_tenant_limit - 3,
    }


def test_generation_regeneration_preserves_original_job_snapshot(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client, teacher, revision, idempotency_key="regeneration-source"
    )
    source = session.get(GenerationJob, UUID(str(created["id"])))
    assert source is not None
    expected_snapshot = (
        source.grade,
        source.subject,
        source.policy_version,
        source.prompt_version,
    )
    draft = fetch_only_draft(client, headers, created["id"])
    revision.objective.grade_mapping.internal_level = "G6"
    revision.objective.subject = "science"
    session.commit()

    response = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/regenerate",
        headers=headers | {"Idempotency-Key": "regeneration-snapshot"},
        json={},
    )

    assert response.status_code == 201
    regenerated = session.get(GenerationJob, UUID(response.json()["id"]))
    assert regenerated is not None
    assert (
        regenerated.grade,
        regenerated.subject,
        regenerated.policy_version,
        regenerated.prompt_version,
    ) == expected_snapshot


def test_teacher_job_request_is_idempotent_and_never_publishes(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "same-request"}
    payload = {
        "curriculum_objective_revision_id": str(revision.id),
        "question_types": ["M1"],
        "requested_count": 1,
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
            "question_types": ["M1"],
            "requested_count": 1,
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
    assert created.json()["subject"] == "mathematics"
    assert job.json()["subject"] == "mathematics"
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
            "question_types": ["M1"],
            "requested_count": 2,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "generation_batch_limit_exceeded"


def test_old_validation_run_is_not_current_after_edit(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "validation-run"}
    teacher_constraint = "private teacher validation constraint"
    created = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 1,
            "teacher_constraint": teacher_constraint,
        },
    )
    draft_id = client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    ).json()["items"][0]["id"]
    monkeypatch.setattr(validation_router, "HttpGraderClient", DeterministicM2Client)

    created_run = client.post(
        f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers
    )

    draft = session.get(GeneratedQuestionDraft, UUID(draft_id))
    assert draft is not None
    initial_revision_id = draft.current_revision_id
    edited_revision = GeneratedQuestionDraftRevision(
        generated_question_draft_id=draft.id,
        revision_number=2,
        candidate_json={**draft.candidate_json, "prompt": "What is 9 + 9?"},
        content_hash="2" * 64,
    )
    session.add(edited_revision)
    session.flush()
    draft.current_revision_id = edited_revision.id
    session.flush()

    current_run = client.post(
        f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers
    )
    history = client.get(f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers)
    fetched = client.get(
        f"/v1/ai-question-validation-runs/{created_run.json()['id']}", headers=headers
    )

    assert created_run.status_code == 201
    assert created_run.json()["revision_number"] == 1
    assert "draft_revision_id" not in created_run.json()
    assert created_run.json()["status"] == "passed"
    difficulty_signal = created_run.json()["feature_summary"]["difficulty_signal"]
    assert difficulty_signal["version"] == "rule-based-difficulty-v1"
    assert difficulty_signal["availability"] == "available"
    assert difficulty_signal["reason"] is None
    assert 0 <= difficulty_signal["target"] <= 1
    assert 0 <= difficulty_signal["estimated"] <= 1
    assert {feature["type"] for feature in difficulty_signal["features"]} >= {
        "question_type_baseline",
        "prompt_units",
        "sentence_units",
    }
    assert "What is 2 + 2?" not in str(difficulty_signal)
    assert "teacher-only" not in str(difficulty_signal)
    assert current_run.status_code == 201
    assert current_run.json()["revision_number"] == 2
    assert [item["revision_number"] for item in history.json()["items"]] == [2, 1]
    assert fetched.json()["revision_number"] == 1
    assert fetched.json()["findings"] == []

    persisted_runs = [
        session.get(GenerationValidationRun, UUID(response.json()["id"]))
        for response in (created_run, current_run)
    ]
    assert all(run is not None for run in persisted_runs)
    internal_hashes = tuple(
        hash_value
        for run in persisted_runs
        if run is not None
        for hash_value in run.feature_summary_json["candidate_prompt_fingerprint"].values()
        if isinstance(hash_value, str)
    )
    assert internal_hashes
    system_prompt = resolve_prompt_template("generator-v1", ["M1"]).system_instructions
    forbidden_values = (
        str(initial_revision_id),
        str(edited_revision.id),
        "What is 2 + 2?",
        "What is 9 + 9?",
        teacher_constraint,
        system_prompt,
        *internal_hashes,
    )
    assert_public_validation_payload_is_sanitized(
        created_run.json(), forbidden_values=forbidden_values
    )
    assert_public_validation_payload_is_sanitized(
        current_run.json(), forbidden_values=forbidden_values
    )
    assert_public_validation_payload_is_sanitized(history.json(), forbidden_values=forbidden_values)
    assert_public_validation_payload_is_sanitized(fetched.json(), forbidden_values=forbidden_values)


def test_validation_run_route_exposes_unavailable_difficulty_signal_without_diagnostics(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, revision = teacher_and_objective(session)
    headers = authorize(client, teacher) | {"Idempotency-Key": "validation-run-unavailable"}
    created = client.post(
        "/v1/ai-question-generation/jobs",
        headers=headers,
        json={
            "curriculum_objective_revision_id": str(revision.id),
            "question_types": ["M1"],
            "requested_count": 1,
        },
    )
    draft_id = client.get(
        f"/v1/ai-question-generation/jobs/{created.json()['id']}/questions", headers=headers
    ).json()["items"][0]["id"]

    def raise_internal_error(*args: object, **kwargs: object) -> object:
        raise RuntimeError("internal route secret diagnostic")

    monkeypatch.setattr(question_verification, "_evaluate_candidate", raise_internal_error)
    response = client.post(
        f"/v1/ai-generated-questions/{draft_id}/validation-runs", headers=headers
    )

    assert response.status_code == 201
    difficulty_signal = response.json()["feature_summary"]["difficulty_signal"]
    assert difficulty_signal == {
        "version": "rule-based-difficulty-v1",
        "availability": "unavailable",
        "target": None,
        "estimated": None,
        "deviation": None,
        "curriculum_range": {"min": None, "max": None},
        "features": [],
        "reason": "validator_unavailable",
    }
    assert "secret" not in str(response.json())
    assert "diagnostic" not in str(response.json())


def test_teacher_lists_and_reads_only_own_generation_jobs_while_tenant_admin_can_read_all(
    client: TestClient, session: Session
) -> None:
    teacher, revision = teacher_and_objective(session)
    owner_headers, created = create_generation_job(
        client,
        teacher,
        revision,
        idempotency_key="authorization-owner-job",
    )
    draft = fetch_only_draft(client, owner_headers, created["id"])
    other_teacher = User(
        tenant_id=teacher.tenant_id,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="other-teacher-subject",
        display_name="Other teacher",
        work_email="other-teacher@example.test",
    )
    admin = User(
        tenant_id=teacher.tenant_id,
        role=Role.ADMIN,
        oidc_issuer=ISSUER,
        oidc_subject="tenant-admin-subject",
        display_name="Tenant admin",
        work_email="admin@example.test",
    )
    session.add_all([other_teacher, admin])
    session.commit()

    other_teacher_headers = authorize(client, other_teacher)
    assert client.get("/v1/ai-question-generation/jobs", headers=other_teacher_headers).json() == {
        "items": [],
        "next_after": None,
    }
    assert (
        client.get(
            f"/v1/ai-question-generation/jobs/{created['id']}", headers=other_teacher_headers
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/v1/ai-question-generation/jobs/{created['id']}/questions",
            headers=other_teacher_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/ai-generated-questions/{draft['id']}/validation-runs",
            headers=other_teacher_headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/v1/ai-generated-questions/{draft['id']}/reject",
            headers=other_teacher_headers | {"Idempotency-Key": "unauthorized-reject"},
            json={"expected_revision_number": 1, "reason": "duplicate"},
        ).status_code
        == 404
    )

    owner_list = client.get("/v1/ai-question-generation/jobs", headers=authorize(client, teacher))
    assert [item["id"] for item in owner_list.json()["items"]] == [created["id"]]
    admin_list = client.get("/v1/ai-question-generation/jobs", headers=authorize(client, admin))
    assert [item["id"] for item in admin_list.json()["items"]] == [created["id"]]


def test_cross_tenant_actor_cannot_discover_jobs_drafts_or_validation_runs(
    client: TestClient, session: Session
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="cross-tenant-source-job",
    )
    draft_payload = fetch_only_draft(client, headers, created["id"])
    draft = session.get(GeneratedQuestionDraft, UUID(str(draft_payload["id"])))
    assert draft is not None
    run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        draft_revision_id=draft.current_revision_id,
        generation_job_id=draft.job_id,
        run_number=1,
        validator_version="api-test",
        ruleset_version="api-test",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={},
    )
    other_tenant = Tenant(slug="other-school", name="Other school")
    other_teacher = User(
        tenant=other_tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="cross-tenant-teacher",
        display_name="Cross-tenant teacher",
        work_email="cross-tenant@example.test",
    )
    session.add_all([run, other_teacher])
    session.commit()
    client.app.dependency_overrides[get_current_principal] = lambda: CurrentPrincipal(
        user_id=str(other_teacher.id),
        tenant_id=str(other_teacher.tenant_id),
        role=other_teacher.role,
        school_id=None,
        display_name=other_teacher.display_name,
        oidc_subject=other_teacher.oidc_subject or "",
    )

    assert client.get("/v1/ai-question-generation/jobs").json() == {
        "items": [],
        "next_after": None,
    }
    job_response = client.get(f"/v1/ai-question-generation/jobs/{created['id']}")
    draft_response = client.post(
        f"/v1/ai-generated-questions/{draft.id}/reject",
        headers={"Idempotency-Key": "cross-tenant-reject"},
        json={"expected_revision_number": 1, "reason": "duplicate"},
    )
    run_response = client.get(f"/v1/ai-question-validation-runs/{run.id}")
    missing_run_response = client.get(f"/v1/ai-question-validation-runs/{uuid4()}")

    assert job_response.status_code == 404
    assert job_response.json()["detail"]["code"] == "generation_job_not_found"
    assert draft_response.status_code == 404
    assert draft_response.json()["detail"]["code"] == "generation_draft_not_found"
    assert run_response.status_code == 404
    assert run_response.json()["detail"]["code"] == "validation_run_not_found"
    assert missing_run_response.status_code == 404
    assert missing_run_response.json()["detail"]["code"] == "validation_run_not_found"


def test_validation_finding_response_uses_explicit_safe_projection(
    client: TestClient, session: Session
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="safe-finding-source-job",
    )
    draft_payload = fetch_only_draft(client, headers, created["id"])
    draft = session.get(GeneratedQuestionDraft, UUID(str(draft_payload["id"])))
    assert draft is not None
    run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        draft_revision_id=draft.current_revision_id,
        generation_job_id=draft.job_id,
        run_number=1,
        validator_version="api-test",
        ruleset_version="api-test",
        status=ValidationRunStatus.WARNING,
        feature_summary_json={},
    )
    finding = ValidationFinding(
        validation_run=run,
        code="grade_complexity_warning",
        severity=ValidationFindingSeverity.WARNING,
        evidence_json={
            "grade_level": "G5",
            "metric": "prompt_units",
            "observed": 12,
            "limit": 10,
            "content_hash": "private-content-hash",
            "request_metadata": {"provider": "private-provider"},
            "exception": "private exception text",
            "candidate": {"prompt": "private candidate body"},
        },
        remediation="private exception text with private candidate body",
    )
    session.add(finding)
    session.commit()

    response = client.get(f"/v1/ai-question-validation-runs/{run.id}", headers=headers)

    assert response.status_code == 200
    public_finding = response.json()["findings"][0]
    assert public_finding["evidence"] == {
        "grade_level": "G5",
        "metric": "prompt_units",
        "observed": 12,
        "limit": 10,
    }
    assert "private" not in str(public_finding).casefold()
    assert "hash" not in str(public_finding).casefold()
    assert "exception" not in str(public_finding).casefold()


def test_revision_api_replays_exact_request_and_rejects_changed_body(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="revision-source-job",
    )
    draft = fetch_only_draft(client, headers, created["id"])
    body = {
        "expected_revision_number": 1,
        "candidate": {**draft["candidate"], "prompt": "What is 8 + 4?"},
    }
    monkeypatch.setattr(generation_router, "HttpGraderClient", DeterministicM2Client)
    write_headers = headers | {"Idempotency-Key": "review-revision-key"}

    first = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/revisions",
        headers=write_headers,
        json=body,
    )
    monkeypatch.setattr(validation_router, "HttpGraderClient", DeterministicM2Client)
    later_validation = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/validation-runs",
        headers=headers,
    )
    replay = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/revisions",
        headers=write_headers,
        json=body,
    )
    conflict = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/revisions",
        headers=write_headers,
        json={**body, "candidate": {**body["candidate"], "prompt": "Changed retry body"}},
    )
    current_draft = fetch_only_draft(client, headers, created["id"])

    assert first.status_code == 201
    assert later_validation.status_code == 201
    assert later_validation.json()["id"] != first.json()["validation_run"]["id"]
    assert replay.status_code == 201
    assert replay.json() == first.json()
    assert first.json()["revision_number"] == 2
    assert first.json()["validation_run"]["revision_number"] == 2
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_conflict"
    assert current_draft["candidate"]["prompt"] == "What is 8 + 4?"
    assert current_draft["revision_number"] == 2
    assert session.scalar(select(func.count(GeneratedQuestionDraftRevision.id))) == 2
    assert "hash" not in str(first.json()).casefold()
    assert "request_summary" not in str(first.json()).casefold()


def test_revision_api_recovers_exact_replay_after_post_lock_unique_conflict(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="unique-conflict-source-job",
    )
    draft = fetch_only_draft(client, headers, created["id"])
    body = {
        "expected_revision_number": 1,
        "candidate": {**draft["candidate"], "prompt": "What is 7 + 5?"},
    }
    original_create_revision = generation_router.create_review_revision

    def persist_competing_request_then_raise(*args: object, **kwargs: object) -> object:
        original_create_revision(*args, **kwargs)
        session.commit()
        raise IntegrityError("forced unique conflict", {}, RuntimeError("duplicate key"))

    monkeypatch.setattr(generation_router, "HttpGraderClient", DeterministicM2Client)
    monkeypatch.setattr(
        generation_router,
        "create_review_revision",
        persist_competing_request_then_raise,
    )

    response = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/revisions",
        headers=headers | {"Idempotency-Key": "post-lock-unique-key"},
        json=body,
    )

    assert response.status_code == 201
    assert response.json()["revision_number"] == 2
    assert response.json()["validation_run"]["revision_number"] == 2
    assert session.scalar(select(func.count(GeneratedQuestionDraftRevision.id))) == 2


def test_reject_api_replays_exact_action_and_conflicts_with_different_action_or_body(
    client: TestClient, session: Session
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="reject-source-job",
    )
    draft = fetch_only_draft(client, headers, created["id"])
    persisted_draft = session.get(GeneratedQuestionDraft, UUID(str(draft["id"])))
    assert persisted_draft is not None
    session.add(
        GenerationValidationRun(
            generated_question_draft_id=persisted_draft.id,
            draft_revision_id=persisted_draft.current_revision_id,
            generation_job_id=persisted_draft.job_id,
            run_number=1,
            validator_version="api-test",
            ruleset_version="api-test",
            status=ValidationRunStatus.PASSED,
            feature_summary_json={},
        )
    )
    session.commit()
    write_headers = headers | {"Idempotency-Key": "review-decision-key"}
    body = {"expected_revision_number": 1, "reason": "duplicate", "detail": None}

    first = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/reject",
        headers=write_headers,
        json=body,
    )
    replay = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/reject",
        headers=write_headers,
        json=body,
    )
    changed_body = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/reject",
        headers=write_headers,
        json={**body, "reason": "unclear_wording"},
    )
    changed_action = client.post(
        f"/v1/ai-generated-questions/{draft['id']}/accept",
        headers=write_headers,
        json={"expected_revision_number": 1, "confirm_warnings": False},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["action"] == "reject"
    assert first.json()["reason"] == "duplicate"
    assert first.json()["revision_number"] == 1
    assert first.json()["validation_run"]["revision_number"] == 1
    assert changed_body.status_code == 409
    assert changed_body.json()["detail"]["code"] == "idempotency_key_conflict"
    assert changed_action.status_code == 409
    assert changed_action.json()["detail"]["code"] == "idempotency_key_conflict"
    assert session.scalar(select(func.count(GeneratedQuestionReviewDecision.id))) == 1


def test_accept_api_requires_current_validation_and_replays_accepted_version(
    client: TestClient, session: Session
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, blocked_job = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="blocked-accept-source-job",
    )
    blocked_draft_payload = fetch_only_draft(client, headers, blocked_job["id"])
    blocked_draft = session.get(GeneratedQuestionDraft, UUID(str(blocked_draft_payload["id"])))
    assert blocked_draft is not None
    blocked_run = GenerationValidationRun(
        generated_question_draft_id=blocked_draft.id,
        draft_revision_id=blocked_draft.current_revision_id,
        generation_job_id=blocked_draft.job_id,
        run_number=1,
        validator_version="api-test",
        ruleset_version="api-test",
        status=ValidationRunStatus.BLOCKED,
        feature_summary_json={"private_exception_detail": "must-not-leak"},
    )
    session.add(blocked_run)
    session.commit()
    blocked = client.post(
        f"/v1/ai-generated-questions/{blocked_draft.id}/accept",
        headers=headers | {"Idempotency-Key": "blocked-accept-key"},
        json={"expected_revision_number": 1, "confirm_warnings": False},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "validation_blocked"

    headers, accepted_job = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="accepted-source-job",
    )
    accepted_draft_payload = fetch_only_draft(client, headers, accepted_job["id"])
    accepted_draft = session.get(GeneratedQuestionDraft, UUID(str(accepted_draft_payload["id"])))
    assert accepted_draft is not None
    passed_run = GenerationValidationRun(
        generated_question_draft_id=accepted_draft.id,
        draft_revision_id=accepted_draft.current_revision_id,
        generation_job_id=accepted_draft.job_id,
        run_number=1,
        validator_version="api-test",
        ruleset_version="api-test",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={},
    )
    session.add(passed_run)
    session.commit()
    write_headers = headers | {"Idempotency-Key": "accepted-review-key"}
    body = {"expected_revision_number": 1, "confirm_warnings": False}

    first = client.post(
        f"/v1/ai-generated-questions/{accepted_draft.id}/accept",
        headers=write_headers,
        json=body,
    )
    replay = client.post(
        f"/v1/ai-generated-questions/{accepted_draft.id}/accept",
        headers=write_headers,
        json=body,
    )
    conflict = client.post(
        f"/v1/ai-generated-questions/{accepted_draft.id}/accept",
        headers=write_headers,
        json={**body, "confirm_warnings": True},
    )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert first.json()["action"] == "accept"
    assert first.json()["accepted_question_version_id"]
    assert first.json()["validation_run"]["status"] == "passed"
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_key_conflict"
    assert session.scalar(select(func.count(QuestionVersion.id))) == 1


def test_accept_api_requires_warning_confirmation_then_persists_confirmed_decision(
    client: TestClient, session: Session
) -> None:
    teacher, objective_revision = teacher_and_objective(session)
    headers, created = create_generation_job(
        client,
        teacher,
        objective_revision,
        idempotency_key="warning-accept-source-job",
    )
    draft_payload = fetch_only_draft(client, headers, created["id"])
    draft = session.get(GeneratedQuestionDraft, UUID(str(draft_payload["id"])))
    assert draft is not None
    session.add(
        GenerationValidationRun(
            generated_question_draft_id=draft.id,
            draft_revision_id=draft.current_revision_id,
            generation_job_id=draft.job_id,
            run_number=1,
            validator_version="api-test",
            ruleset_version="api-test",
            status=ValidationRunStatus.WARNING,
            feature_summary_json={},
        )
    )
    session.commit()

    without_confirmation = client.post(
        f"/v1/ai-generated-questions/{draft.id}/accept",
        headers=headers | {"Idempotency-Key": "warning-not-confirmed"},
        json={"expected_revision_number": 1, "confirm_warnings": False},
    )
    with_confirmation = client.post(
        f"/v1/ai-generated-questions/{draft.id}/accept",
        headers=headers | {"Idempotency-Key": "warning-confirmed"},
        json={"expected_revision_number": 1, "confirm_warnings": True},
    )

    assert without_confirmation.status_code == 409
    assert without_confirmation.json()["detail"]["code"] == "warning_confirmation_required"
    assert with_confirmation.status_code == 200
    assert with_confirmation.json()["accepted_question_version_id"]
    decision = session.scalar(
        select(GeneratedQuestionReviewDecision).where(
            GeneratedQuestionReviewDecision.generated_question_draft_id == draft.id
        )
    )
    assert decision is not None
    assert decision.warning_confirmed is True
