from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from uuid import UUID, uuid4

import pytest
from edu_generator import prompt_templates
from edu_generator.contracts import (
    GeneratedCandidateEnvelope,
    GenerationPlanItem,
    GenerationRequest,
    ProviderFailure,
)
from edu_generator.prompt_templates import PromptTemplate, resolve_prompt_template
from edu_generator.providers import FakeGenerationProvider
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import edu_grader_api.services.generation as generation_service
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
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationAttempt,
    GenerationControlState,
    GenerationDefaultChangeRequest,
    GenerationDefaultChangeStatus,
    GenerationDefaultConfiguration,
    GenerationDefaultSelection,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    GenerationJob,
    GenerationJobStatus,
    Role,
    Tenant,
    User,
    utc_now,
)
from edu_grader_api.policies import validate_policy
from edu_grader_api.services.generation import (
    GENERATION_PROMPT_VERSION,
    GenerationJobRequest,
    GenerationServiceError,
    _content_hash,
    _provider_request,
    _request_digest,
    _request_summary,
    create_or_get_job,
    run_generation_job,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        template = resolve_prompt_template("generator-v1", ("M1", "M2", "E1", "E2", "E3", "E4"))
        configuration = GenerationDefaultConfiguration(
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            prompt_template_fingerprint=template.fingerprint,
            created_by_user_id=uuid4(),
        )
        request = GenerationDefaultChangeRequest(
            configuration=configuration,
            status=GenerationDefaultChangeStatus.APPLIED,
            request_reason="Test default",
            idempotency_key="test-default",
            request_digest="a" * 64,
            evaluation_report_sha256="b" * 64,
            evaluation_record_digest="c" * 64,
            evaluation_run_id="run",
            evaluation_spec_id="spec",
            evaluation_watermark=utc_now(),
            evaluation_summary_json={},
            submitted_by_user_id=uuid4(),
        )
        session.add_all(
            [
                configuration,
                request,
                GenerationDefaultSelection(
                    scope="global",
                    configuration=configuration,
                    applied_change_request=request,
                ),
            ]
        )
        session.flush()
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
        items=[
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="standard",
                target_difficulty=0.5,
            ),
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="standard",
                target_difficulty=0.5,
            ),
        ],
        requested_count=2,
        idempotency_key="same-request",
        teacher_constraint=teacher_constraint,
    )


def teacher_and_e4_objective(session: Session) -> tuple[User, CurriculumObjectiveRevision]:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E4"]
    return teacher, revision


def add_governance_entry(
    session: Session,
    *,
    tenant_id: UUID | None,
    target_type: GenerationGovernanceTargetType,
    target_key: str,
    control_state: GenerationControlState,
    is_global: bool = False,
    created_by_user_id: UUID | None = None,
) -> None:
    session.add(
        GenerationGovernanceEntry(
            tenant_id=tenant_id if not is_global else None,
            target_type=target_type,
            target_key=target_key,
            control_state=control_state,
            is_global=is_global,
            created_by_user_id=created_by_user_id,
        )
    )


def e4_generation_request(revision: CurriculumObjectiveRevision) -> GenerationJobRequest:
    return GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="E4",
                difficulty_band="standard",
                target_difficulty=0.5,
            )
        ],
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
                    "difficulty": 0.5,
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
        items=[
            GenerationPlanItem(
                question_type=question_type,
                difficulty_band="standard",
                target_difficulty=0.5,
            )
            for question_type in ["M1", "M2", "E1", "E4"]
        ],
        requested_count=4,
        policy_version="2026.07",
        prompt_version="generator-v1",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert all(
        not validate_policy(candidate.question_type, candidate.policy_version, candidate.rule_json)
        for candidate in result.candidates
    )


def test_fake_provider_preserves_ordered_generation_plan() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        objective_text="Add within 100.",
        difficulty_min=0,
        difficulty_max=1,
        grade="G7",
        subject="mathematics",
        items=[
            GenerationPlanItem(
                question_type="M1", difficulty_band="foundation", target_difficulty=0.2
            ),
            GenerationPlanItem(
                question_type="M2", difficulty_band="stretch", target_difficulty=0.8
            ),
        ],
        requested_count=2,
        policy_version="2026.07",
        prompt_version="generator-v1",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert [item.question_type for item in result.candidates] == ["M1", "M2"]
    assert [item.difficulty for item in result.candidates] == [0.2, 0.8]


def test_generation_request_requires_an_item_for_every_requested_candidate() -> None:
    with pytest.raises(ValidationError, match="generation plan item count"):
        GenerationRequest(
            objective_revision_id=uuid4(),
            objective_text="Add within 100.",
            difficulty_min=0,
            difficulty_max=1,
            grade="G7",
            subject="mathematics",
            items=[
                GenerationPlanItem(
                    question_type="M1",
                    difficulty_band="foundation",
                    target_difficulty=0.2,
                )
            ],
            requested_count=2,
            policy_version="2026.07",
            prompt_version="generator-v1",
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
    assert GENERATION_PROMPT_VERSION == "generator-v1"
    assert job.prompt_version == "generator-v1"


def test_creation_persists_server_owned_difficulty_plan(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    request = GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="foundation",
                target_difficulty=0.2,
            ),
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="stretch",
                target_difficulty=0.8,
            ),
        ],
        requested_count=2,
        idempotency_key="difficulty-plan",
    )

    job = create_or_get_job(session, request=request, actor=teacher)

    assert job.distribution_json["items"] == [
        {
            "question_type": "M1",
            "difficulty_band": "foundation",
            "target_difficulty": 0.2,
        },
        {
            "question_type": "M1",
            "difficulty_band": "stretch",
            "target_difficulty": 0.8,
        },
    ]


def test_generation_request_rejects_server_owned_snapshot_fields(
    session: Session,
) -> None:
    _, revision = teacher_and_objective(session)

    with pytest.raises(ValidationError):
        GenerationJobRequest(
            curriculum_objective_revision_id=revision.id,
            items=[
                GenerationPlanItem(
                    question_type="M1",
                    difficulty_band="standard",
                    target_difficulty=0.5,
                )
            ],
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
    invalid_item = GenerationPlanItem.model_construct(
        question_type="X1",
        difficulty_band="standard",
        target_difficulty=0.5,
    )
    request = generation_request(revision).model_copy(
        update={"items": [invalid_item, invalid_item]}
    )

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
    request_data["items"] = [
        {
            "question_type": "E1",
            "difficulty_band": "standard",
            "target_difficulty": 0.5,
        }
    ]
    request_data["requested_count"] = 1
    request = GenerationJobRequest.model_validate(request_data)
    template = resolve_prompt_template(GENERATION_PROMPT_VERSION, ["M1"])
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
    assert [item.question_type for item in provider.request.items] == ["M1", "M1"]
    assert [item.difficulty_band for item in provider.request.items] == [
        "standard",
        "standard",
    ]
    assert [item.target_difficulty for item in provider.request.items] == [0.5, 0.5]
    assert provider.request.requested_count == job.requested_count


def test_difficulty_plan_discards_candidates_that_miss_their_ordinal_plan(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    request = GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="foundation",
                target_difficulty=0.2,
            ),
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="stretch",
                target_difficulty=0.8,
            ),
        ],
        requested_count=2,
        idempotency_key="difficulty-plan-ordinal-enforcement",
    )
    job = create_or_get_job(session, request=request, actor=teacher)
    result = GeneratedCandidateEnvelope.from_provider_payload(
        {
            "provider_name": "fake",
            "model_version": "fake-v1",
            "candidates": [
                {
                    "objective_revision_id": str(revision.id),
                    "question_type": "M1",
                    "policy_version": "1",
                    "prompt": "This misses the foundation target.",
                    "rule_json": {"expected": 4, "tolerance": 0},
                    "explanation": "The reported difficulty belongs to another plan item.",
                    "knowledge_point": "whole-number addition",
                    "difficulty": 0.75,
                },
                {
                    "objective_revision_id": str(revision.id),
                    "question_type": "M1",
                    "policy_version": "1",
                    "prompt": "This matches ordinal two.",
                    "rule_json": {"expected": 4, "tolerance": 0},
                    "explanation": "The type and difficulty match ordinal two.",
                    "knowledge_point": "whole-number addition",
                    "difficulty": 0.75,
                },
            ],
        }
    )

    run_generation_job(session, job=job, provider=CapturingProvider(result))

    assert job.succeeded_count == 1
    assert [draft.ordinal for draft in job.drafts] == [2]


def test_generation_records_safe_reason_when_candidate_misses_objective(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    request = GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="M1",
                difficulty_band="standard",
                target_difficulty=0.5,
            )
        ],
        requested_count=1,
        idempotency_key="rejection-reason-objective",
    )
    job = create_or_get_job(session, request=request, actor=teacher)
    candidate = (
        valid_single_candidate(revision)
        .candidates[0]
        .model_copy(update={"objective_revision_id": uuid4(), "prompt": "private invalid prompt"})
    )
    result = GeneratedCandidateEnvelope(
        provider_name="fake",
        model_version="fake-v1",
        candidates=[candidate],
    )

    run_generation_job(session, job=job, provider=CapturingProvider(result))

    assert job.status is GenerationJobStatus.FAILED
    assert job.failure_code == "candidate_validation_failed"
    assert job.attempts[0].response_summary == {
        "candidate_count": 1,
        "candidate_rejections": [{"ordinal": 1, "code": "objective_revision_mismatch"}],
    }
    assert "private invalid prompt" not in str(job.attempts[0].response_summary)


def test_generation_records_safe_policy_schema_diagnostic_for_e1(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E1"]
    request = GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="E1",
                difficulty_band="standard",
                target_difficulty=0.5,
            )
        ],
        requested_count=1,
        idempotency_key="rejection-reason-e1-policy",
    )
    job = create_or_get_job(session, request=request, actor=teacher)
    candidate = (
        valid_single_candidate(revision)
        .candidates[0]
        .model_copy(
            update={
                "question_type": "E1",
                "policy_version": "2",
                "prompt": "Name the color of the sky on a clear day.",
                "rule_json": {"accepted_answers": ["blue"], "ignore_case": True},
                "explanation": "A clear daytime sky is blue.",
            }
        )
    )
    result = GeneratedCandidateEnvelope(
        provider_name="fake",
        model_version="fake-v1",
        candidates=[candidate],
    )

    run_generation_job(session, job=job, provider=CapturingProvider(result))

    assert job.status is GenerationJobStatus.FAILED
    assert job.attempts[0].response_summary == {
        "candidate_count": 1,
        "candidate_rejections": [
            {
                "ordinal": 1,
                "code": "policy_rule_invalid",
                "rule_path": "/",
                "rule_keyword": "additionalProperties",
            }
        ],
    }
    assert "blue" not in str(job.attempts[0].response_summary)


def test_generation_deduplicates_e1_answers_using_policy_normalization(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    revision.allowed_question_types = ["E1"]
    request = GenerationJobRequest(
        curriculum_objective_revision_id=revision.id,
        items=[
            GenerationPlanItem(
                question_type="E1",
                difficulty_band="standard",
                target_difficulty=0.5,
            )
        ],
        requested_count=1,
        idempotency_key="deduplicate-e1-normalized-answers",
    )
    job = create_or_get_job(session, request=request, actor=teacher)
    candidate = (
        valid_single_candidate(revision)
        .candidates[0]
        .model_copy(
            update={
                "question_type": "E1",
                "policy_version": "2",
                "prompt": "What color is the ball?",
                "rule_json": {
                    "accepted_answers": ["red", " Red. "],
                    "normalization": {
                        "unicode_form": "NFKC",
                        "collapse_whitespace": True,
                        "ignore_case": True,
                        "ignore_terminal_punctuation": True,
                    },
                },
                "explanation": "The ball is red.",
            }
        )
    )

    run_generation_job(
        session,
        job=job,
        provider=CapturingProvider(
            GeneratedCandidateEnvelope(
                provider_name="fake", model_version="fake-v1", candidates=[candidate]
            )
        ),
    )

    assert job.status is GenerationJobStatus.READY_FOR_REVIEW
    assert job.drafts[0].candidate_json["rule_json"] == {
        "accepted_answers": ["red"],
        "normalization": {
            "unicode_form": "NFKC",
            "collapse_whitespace": True,
            "ignore_case": True,
            "ignore_terminal_punctuation": True,
        },
    }


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

    template = resolve_prompt_template(GENERATION_PROMPT_VERSION, ["M1"])
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


def test_job_with_changed_prompt_fingerprint_fails_without_creating_an_attempt(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    job.prompt_template_fingerprint = "0" * 64
    session.flush()

    provider = FailIfCalledProvider()
    run_generation_job(session, job=job, provider=provider)

    assert job.status is GenerationJobStatus.FAILED
    assert job.failure_code == "prompt_template_changed"
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


@pytest.mark.parametrize(
    "state",
    [GenerationControlState.CANARY, GenerationControlState.PAUSED, GenerationControlState.RETIRED],
)
def test_generation_pipeline_blocks_prompt_control_state(
    session: Session, state: GenerationControlState
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    add_governance_entry(
        session,
        tenant_id=teacher.tenant_id,
        target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
        target_key=GENERATION_PROMPT_VERSION,
        control_state=state,
        is_global=True,
    )

    provider = FailIfCalledProvider()
    run_generation_job(session, job=job, provider=provider)

    assert job.status is GenerationJobStatus.FAILED
    assert job.failure_code == "prompt_version_control_blocked"
    assert provider.calls == 0


def test_generation_pipeline_allows_tenant_canary_to_override_global_prompt_canary(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    add_governance_entry(
        session,
        tenant_id=teacher.tenant_id,
        target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
        target_key=GENERATION_PROMPT_VERSION,
        control_state=GenerationControlState.CANARY,
        is_global=True,
    )
    add_governance_entry(
        session,
        tenant_id=teacher.tenant_id,
        target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
        target_key=GENERATION_PROMPT_VERSION,
        control_state=GenerationControlState.CANARY,
        is_global=False,
    )

    job = create_or_get_job(session, request=generation_request(revision), actor=teacher)
    run_generation_job(session, job=job, provider=FakeGenerationProvider(seed=7))

    assert job.status is GenerationJobStatus.READY_FOR_REVIEW
    assert len(job.drafts) == 2


def test_generation_pipeline_blocks_provider_and_model_for_governed_entries(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    add_governance_entry(
        session,
        tenant_id=teacher.tenant_id,
        target_type=GenerationGovernanceTargetType.PROVIDER,
        target_key="fake",
        control_state=GenerationControlState.PAUSED,
        is_global=True,
    )
    add_governance_entry(
        session,
        tenant_id=teacher.tenant_id,
        target_type=GenerationGovernanceTargetType.MODEL,
        target_key="fake-v1",
        control_state=GenerationControlState.PAUSED,
        is_global=True,
    )

    with pytest.raises(GenerationServiceError) as error:
        create_or_get_job(session, request=generation_request(revision), actor=teacher)

    assert str(error.value) in {"provider_control_blocked", "model_control_blocked"}


def _generation_job_for_diversity_test(
    session: Session,
    *,
    teacher: User,
    revision: CurriculumObjectiveRevision,
    idempotency_key: str,
) -> GenerationJob:
    request = generation_request(revision).model_copy(update={"idempotency_key": idempotency_key})
    return create_or_get_job(session, request=request, actor=teacher)


def _add_draft_revision_for_diversity_test(
    session: Session,
    *,
    job: GenerationJob,
    ordinal: int,
    current_prompt: object,
    created_at: datetime,
    teacher_state: str = "pending_review",
) -> GeneratedQuestionDraft:
    attempt = GenerationAttempt(
        job=job,
        attempt_number=ordinal,
        provider_name="test",
        model_version="test-v1",
        prompt_version=GENERATION_PROMPT_VERSION,
        status="succeeded",
    )
    draft = GeneratedQuestionDraft(
        job=job,
        generation_attempt=attempt,
        ordinal=ordinal,
        content_hash=f"draft-{job.id}-{ordinal}",
        candidate_json={"prompt": "stale draft prompt"},
        teacher_state=teacher_state,
        created_at=created_at,
    )
    session.add_all([attempt, draft])
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=draft.current_revision_id,
            generated_question_draft_id=draft.id,
            revision_number=1,
            candidate_json={"prompt": current_prompt},
            content_hash=f"revision-{job.id}-{ordinal}",
            created_at=created_at,
        )
    )
    session.flush()
    return draft


def test_recent_pending_avoid_prompts_uses_only_matching_current_pending_revisions(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-current"
    )
    qualifying_job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-qualifying"
    )
    now = datetime.now(UTC)
    _add_draft_revision_for_diversity_test(
        session,
        job=qualifying_job,
        ordinal=1,
        current_prompt="  Use the current edited prompt.  ",
        created_at=now,
    )
    _add_draft_revision_for_diversity_test(
        session,
        job=qualifying_job,
        ordinal=2,
        current_prompt="Rejected prompt",
        teacher_state="rejected",
        created_at=now + timedelta(seconds=1),
    )
    _add_draft_revision_for_diversity_test(
        session,
        job=job,
        ordinal=1,
        current_prompt="Current job prompt",
        created_at=now + timedelta(seconds=2),
    )

    other_tenant = Tenant(slug="other", name="Other")
    other_teacher = User(
        tenant=other_tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="other-teacher",
        display_name="Other Teacher",
        work_email="other@example.test",
    )
    session.add(other_teacher)
    session.flush()
    other_tenant_job = _generation_job_for_diversity_test(
        session,
        teacher=other_teacher,
        revision=revision,
        idempotency_key="diversity-other-tenant",
    )
    _add_draft_revision_for_diversity_test(
        session,
        job=other_tenant_job,
        ordinal=1,
        current_prompt="Other tenant prompt",
        created_at=now + timedelta(seconds=3),
    )
    other_objective = CurriculumObjective(
        profile=revision.objective.profile,
        grade_mapping=revision.objective.grade_mapping,
        code="MATH-G5-002",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    other_revision = CurriculumObjectiveRevision(
        objective=other_objective,
        revision_number=1,
        text="Use whole numbers over 100.",
        source_locator="section 2",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add(other_revision)
    session.flush()
    other_objective_job = _generation_job_for_diversity_test(
        session,
        teacher=teacher,
        revision=other_revision,
        idempotency_key="diversity-other-objective",
    )
    _add_draft_revision_for_diversity_test(
        session,
        job=other_objective_job,
        ordinal=1,
        current_prompt="Other objective prompt",
        created_at=now + timedelta(seconds=4),
    )

    assert generation_service._recent_pending_avoid_prompts(session, job=job) == [
        "Use the current edited prompt."
    ]


def test_recent_pending_avoid_prompts_bounds_dedupes_and_summary_stays_private(
    session: Session,
) -> None:
    teacher, revision = teacher_and_objective(session)
    job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-request"
    )
    reference_job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-references"
    )
    now = datetime.now(UTC)
    for ordinal in range(1, 22):
        prompt: object = f"Prompt {ordinal}"
        if ordinal == 21:
            prompt = "Oldest prompt outside scan"
        elif ordinal == 5:
            prompt = " " * 3
        elif ordinal == 4:
            prompt = 99
        elif ordinal == 3:
            prompt = "  prompt 2  "
        elif ordinal == 1:
            prompt = "x" * 1_205
        _add_draft_revision_for_diversity_test(
            session,
            job=reference_job,
            ordinal=ordinal,
            current_prompt=prompt,
            created_at=now + timedelta(seconds=22 - ordinal),
        )

    avoid_prompts = generation_service._recent_pending_avoid_prompts(session, job=job)

    assert avoid_prompts == [
        "x" * 1_200,
        "Prompt 2",
        "Prompt 6",
        "Prompt 7",
        "Prompt 8",
        "Prompt 9",
        "Prompt 10",
        "Prompt 11",
    ]
    assert "Oldest prompt outside scan" not in avoid_prompts

    request = _provider_request(session, job, teacher_constraint=None)
    template = resolve_prompt_template(
        request.prompt_version, [item.question_type for item in request.items]
    )
    summary = _request_summary(request, requested_count=job.requested_count, template=template)

    assert request.avoid_prompts == avoid_prompts
    assert summary["avoid_prompt_count"] == 8
    assert summary["avoid_prompt_max_length"] == 1_200
    serialized_summary = str(summary)
    assert "Prompt 2" not in serialized_summary
    assert "x" * 20 not in serialized_summary


def test_recent_pending_avoid_prompts_skips_stored_pii(session: Session) -> None:
    teacher, revision = teacher_and_objective(session)
    job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-pii-request"
    )
    reference_job = _generation_job_for_diversity_test(
        session, teacher=teacher, revision=revision, idempotency_key="diversity-pii-reference"
    )
    now = datetime.now(UTC)
    _add_draft_revision_for_diversity_test(
        session,
        job=reference_job,
        ordinal=1,
        current_prompt="Call 13800138000 before solving.",
        created_at=now,
    )
    _add_draft_revision_for_diversity_test(
        session,
        job=reference_job,
        ordinal=2,
        current_prompt="Use a number line to compare values.",
        created_at=now - timedelta(seconds=1),
    )

    assert generation_service._recent_pending_avoid_prompts(session, job=job) == [
        "Use a number line to compare values."
    ]
