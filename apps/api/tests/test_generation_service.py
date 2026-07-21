from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_generator.contracts import GeneratedCandidateEnvelope, GenerationRequest, ProviderFailure
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
    GenerationJobStatus,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.generation import (
    GenerationJobRequest,
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


def generation_request(revision: CurriculumObjectiveRevision) -> GenerationJobRequest:
    return GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        grade="Grade 5",
        subject="mathematics",
        question_types=["M1"],
        requested_count=2,
        idempotency_key="same-request",
        policy_catalog_version="2026.07",
        prompt_version="generator-v1",
        teacher_constraint="Use only whole numbers under 100.",
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


def test_fake_provider_candidates_match_current_platform_policy_versions() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        grade="Grade 5",
        subject="mathematics",
        question_types=["M1", "M2", "E1", "E4"],
        policy_version="2026.07",
        prompt_version="generator-v1",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert all(
        not validate_policy(candidate.question_type, candidate.policy_version, candidate.rule_json)
        for candidate in result.candidates
    )


def test_creation_replays_a_matching_idempotency_key(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    request = generation_request(revision)

    first = create_or_get_job(session, request=request, actor=teacher)
    second = create_or_get_job(session, request=request, actor=teacher)

    assert second.id == first.id
    assert first.status is GenerationJobStatus.QUEUED


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
