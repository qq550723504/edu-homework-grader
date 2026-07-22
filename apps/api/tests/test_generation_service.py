from types import MappingProxyType
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import edu_generator.prompt_templates as prompt_templates
from edu_generator.contracts import GeneratedCandidateEnvelope, GenerationRequest, ProviderFailure
from edu_generator.prompt_templates import PromptTemplate, resolve_prompt_template
from edu_generator.providers import FakeGenerationProvider
from edu_grader_api.models import (
    Base,
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
    Role,
    Tenant,
    User,
    utc_now,
)
from edu_grader_api.services.generation import (
    GenerationJobRequest,
    GenerationServiceError,
    _content_hash,
    _request_digest,
    create_or_get_job,
    run_generation_job,
)
from edu_grader_api.policies import validate_policy


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def teacher_and_objective(session: Session) -> tuple[User, CurriculumObjectiveRevision]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    source = CurriculumSourceRecord(
        issuer="Example Board",
        title="Math curriculum",
        canonical_url="https://curriculum.example.test/math",
        version_label="2026",
    )
    profile = CurriculumProfile(
        code="pilot-math-2026",
        name="Pilot Mathematics",
        jurisdiction="pilot",
        version_label="2026",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
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
    session.flush()
    return teacher, revision


def generation_request(
    revision: CurriculumObjectiveRevision, *, teacher_constraint: str | None = None
) -> GenerationJobRequest:
    return GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        question_types=["M1", "M1"],
        requested_count=2,
        idempotency_key="same-request",
        teacher_constraint=teacher_constraint,
    )


def teacher_and_e4_objective(session: Session) -> tuple[User, CurriculumObjectiveRevision]:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E4"]
    return teacher, revision


def e4_generation_request(revision: CurriculumObjectiveRevision) -> GenerationJobRequest:
    return GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        question_types=["E4"],
        requested_count=1,
        idempotency_key="e4-reading-material",
    )


def valid_single_candidate(revision: CurriculumObjectiveRevision) -> GeneratedCandidateEnvelope:
    return GeneratedCandidateEnvelope.from_provider_payload(
        {
            "provider_name": "fake",
            "model_version": "fake-v1",
            "candidates": [
                {
                    "objective_revision_id": str(revision.id),
                    "question_type": "M1",
                    "policy_version": "1",
                    "prompt": "What is 2 + 2?",
                    "rule_json": {"expected": 4, "tolerance": 0},
                    "explanation": "Add the two whole numbers.",
                    "knowledge_point": "whole-number addition",
                    "difficulty": 0.2,
                }
            ],
        }
    )


class TimeoutThenSingleCandidate:
    provider_name = "fake"
    model_version = "fake-v1"

    def __init__(self, result: GeneratedCandidateEnvelope) -> None:
        self.result = result
        self.calls = 0

    def generate(self, request: object) -> GeneratedCandidateEnvelope:
        self.calls += 1
        if self.calls == 1:
            raise ProviderFailure("provider_timeout", "timed out", retryable=True)
        return self.result


class CapturingProvider:
    provider_name = "fake"
    model_version = "fake-v1"

    def __init__(self, result: GeneratedCandidateEnvelope) -> None:
        self.result = result
        self.request: GenerationRequest | None = None

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope:
        self.request = request
        return self.result


class FailIfCalledProvider:
    provider_name = "fake"
    model_version = "fake-v1"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope:
        self.calls += 1
        raise AssertionError("unavailable prompt templates must not call the provider")


class CancellingProvider:
    provider_name = "fake"
    model_version = "fake-v1"

    def __init__(self, job: object, result: GeneratedCandidateEnvelope) -> None:
        self.job = job
        self.result = result

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope:
        self.job.cancel_requested_at = utc_now()
        return self.result


def test_fake_provider_candidates_match_current_platform_policy_versions() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        objective_text="Use whole numbers under 100.",
        difficulty_min=0,
        difficulty_max=1,
        grade="Grade 5",
        subject="mathematics",
        question_types=["M1", "M2", "E1", "E4"],
        requested_count=4,
        policy_version="2026.07",
        prompt_version="generator-v1",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert all(
        not validate_policy(candidate.question_type, candidate.policy_version, candidate.rule_json)
        for candidate in result.candidates
    )


def test_e4_material_is_persisted_and_part_of_candidate_hash(session: Session) -> None:
    teacher, revision = teacher_and_e4_objective(session)
    job = create_or_get_job(session, request=e4_generation_request(revision), actor=teacher)

    run_generation_job(session, job=job, provider=FakeGenerationProvider(seed=7))

    draft = job.drafts[0]
    assert draft.candidate_json["reading_material"]
    assert draft.content_hash == _content_hash(draft.candidate_json)


def test_creation_replays_a_matching_idempotency_key(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    request = generation_request(revision)

    first = create_or_get_job(session, request=request, actor=teacher)
    second = create_or_get_job(session, request=request, actor=teacher)

    assert second.id == first.id
    assert first.status is GenerationJobStatus.QUEUED


def test_creation_derives_course_and_versions_from_active_objective(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)

    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)

    assert job.grade == revision.objective.grade_mapping.internal_level
    assert job.subject == revision.objective.subject
    assert job.policy_version == "2026.07"
    assert job.prompt_version == "generator-v1"


def test_generation_request_rejects_server_owned_snapshot_fields(
    session: Session,
) -> None:
    _, revision = teacher_and_objective(session)

    with pytest.raises(ValidationError):
        GenerationJobRequest(
            curriculum_objective_revision_id=revision.id,
            question_types=["M1"],
            requested_count=1,
            idempotency_key="server-owned-snapshot-fields",
            grade="forged-grade",
            subject="forged-subject",
            policy_catalog_version="forged-catalog",
            prompt_version="forged-prompt",
        )


@pytest.mark.parametrize(
    "teacher_constraint",
    [
        "Make it easier for alex@example.test.",
        "Use this phone number: +65 8123 4567.",
        "Student ID: S-1001 needs extra practice.",
    ],
)
def test_generation_rejects_pii_teacher_constraint_before_calling_provider(
    session: Session, teacher_constraint: str
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    provider = FailIfCalledProvider()

    with pytest.raises(GenerationServiceError) as exc_info:
        run_generation_job(
            session,
            job=job,
            provider=provider,
            teacher_constraint=teacher_constraint,
        )

    assert str(exc_info.value) == "teacher_constraint_contains_pii"
    assert provider.calls == 0


def test_creation_rejects_an_inactive_objective_revision(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    revision.status = CurriculumRevisionStatus.DRAFT

    with pytest.raises(GenerationServiceError, match="active"):
        create_or_get_job(session, request=generation_request(revision), actor=teacher)


def test_creation_defensively_rejects_invalid_question_types_before_persisting_a_job(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    request = generation_request(revision).model_copy(update={"question_types": ["X1", "X1"]})

    with pytest.raises(GenerationServiceError) as exc_info:
        create_or_get_job(session, request=request, actor=teacher)

    assert str(exc_info.value) == "requested question types are not allowed by the objective"
    assert session.scalars(select(GenerationJob)).all() == []


def test_creation_rejects_a_normal_request_outside_the_catalog_template_scope(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E1"]
    request_data = generation_request(revision).model_dump()
    request_data["question_types"] = ["E1"]
    request_data["requested_count"] = 1
    request = GenerationJobRequest.model_validate(request_data)
    template = resolve_prompt_template("generator-v1", ["M1"])
    monkeypatch.setattr(
        prompt_templates,
        "PROMPT_TEMPLATE_CATALOG",
        MappingProxyType(
            {
                template.version: PromptTemplate(
                    version=template.version,
                    system_instructions=template.system_instructions,
                    schema_version=template.schema_version,
                    allowed_question_types=frozenset({"M1"}),
                    profile_scope=template.profile_scope,
                )
            }
        ),
    )

    with pytest.raises(GenerationServiceError) as exc_info:
        create_or_get_job(session, request=request, actor=teacher)

    assert str(exc_info.value) == "prompt template is not available for this request"
    assert session.scalars(select(GenerationJob)).all() == []


def test_matching_idempotency_replay_survives_a_historical_prompt_template(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    request = generation_request(revision)
    job = create_or_get_job(session, request=request, actor=teacher)
    job.prompt_version = "historical-template-v0"
    job.request_digest = _request_digest(request)
    session.flush()

    replay = create_or_get_job(session, request=request, actor=teacher)

    assert replay.id == job.id


def test_idempotency_replay_precedes_active_objective_validation(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    request = generation_request(revision)
    first = create_or_get_job(session, request=request, actor=teacher)
    revision.status = CurriculumRevisionStatus.DRAFT

    replay = create_or_get_job(session, request=request, actor=teacher)

    assert replay.id == first.id


def test_idempotency_key_rejects_a_changed_teacher_constraint(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    create_or_get_job(
        session,
        request=generation_request(revision, teacher_constraint="Use sums below ten."),
        actor=teacher,
    )

    with pytest.raises(GenerationServiceError, match="idempotency"):
        create_or_get_job(
            session,
            request=generation_request(revision, teacher_constraint="Use sums below one hundred."),
            actor=teacher,
        )


def test_provider_receives_active_objective_context_and_requested_count(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    provider = CapturingProvider(valid_single_candidate(revision))

    run_generation_job(session, job=job, provider=provider)

    assert provider.request is not None
    assert provider.request.objective_text == revision.text
    assert provider.request.difficulty_min == revision.difficulty_min
    assert provider.request.difficulty_max == revision.difficulty_max
    assert provider.request.requested_count == job.requested_count


def test_successful_attempt_records_template_audit_metadata_without_prompt_body(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    teacher_constraint = "teacher-constraint-secret"
    job = create_or_get_job(
        session,
        request=generation_request(revision, teacher_constraint=teacher_constraint),
        actor=teacher,
    )

    run_generation_job(
        session,
        job=job,
        provider=FakeGenerationProvider(seed=7),
        teacher_constraint=teacher_constraint,
    )

    template = resolve_prompt_template("generator-v1", ["M1"])
    summary = job.attempts[0].request_summary
    assert summary is not None
    assert summary["prompt_template"] == {
        "version": template.version,
        "schema_version": template.schema_version,
        "profile_scope": template.profile_scope,
        "allowed_question_types": sorted(template.allowed_question_types),
        "fingerprint": template.fingerprint,
    }
    assert template.system_instructions not in str(summary)
    assert "teacher_constraint" not in summary
    assert teacher_constraint not in str(summary)


def test_historical_job_with_unavailable_template_fails_without_creating_an_attempt(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    job.prompt_version = "historical-template-v0"
    session.flush()

    provider = FailIfCalledProvider()
    run_generation_job(session, job=job, provider=provider)

    assert job.status is GenerationJobStatus.FAILED
    assert job.failure_code == "prompt_template_unavailable"
    assert job.failed_count == job.requested_count
    assert job.attempts == []
    assert provider.calls == 0


def test_cancellation_after_provider_returns_does_not_persist_a_draft(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)

    run_generation_job(
        session,
        job=job,
        provider=CancellingProvider(job, valid_single_candidate(revision)),
    )

    assert job.status is GenerationJobStatus.CANCELLED
    assert job.drafts == []


def test_timeout_retries_once_then_records_partial_failure_without_identity_data(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    provider = TimeoutThenSingleCandidate(valid_single_candidate(revision))

    run_generation_job(session, job=job, provider=provider)

    assert job.status is GenerationJobStatus.PARTIALLY_FAILED
    assert len(job.attempts) == 2
    assert len(job.drafts) == 1
    assert all(
        "student_id" not in (attempt.request_summary or {})
        and "display_name" not in (attempt.request_summary or {})
        for attempt in job.attempts
    )
