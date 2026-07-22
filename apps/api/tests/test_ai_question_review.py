from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from edu_grader_api.auth import CurrentPrincipal
from edu_grader_api.models import (
    AuditLog,
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
    GeneratedQuestionReviewDecision,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    GenerationValidationRun,
    QuestionTestRun,
    QuestionVersion,
    Role,
    Tenant,
    User,
    ValidationRunStatus,
    VersionStatus,
)
from edu_grader_api.services.ai_question_review import (
    ReviewAccessError,
    ReviewConflictError,
    ReviewStateError,
    accept_review_draft,
    create_review_revision,
    reject_review_draft,
)
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.routers.questions import list_question_versions_route


class PassingGrader:
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        del question_type, policy_version
        text = answer_json.get("text")
        expected = rule_json["expected"]
        tolerance = rule_json.get("tolerance", 0)
        try:
            accepted = bool(text) and abs(float(str(text)) - float(expected)) <= float(tolerance)
        except ValueError:
            accepted = False
        return GradeResult(
            "auto_accepted" if accepted else "auto_rejected",
            1 if accepted else 0,
            {},
            "test-grader-v1",
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def review_draft(session: Session) -> tuple[GeneratedQuestionDraft, User]:
    tenant = Tenant(slug=f"pilot-{uuid4()}", name="Pilot")
    actor = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject=str(uuid4()),
        display_name="Teacher",
        work_email=f"teacher-{uuid4()}@example.test",
    )
    source = CurriculumSourceRecord(
        issuer="Example Board",
        title="Math curriculum",
        canonical_url="https://curriculum.example.test/math",
        version_label="2026",
    )
    profile = CurriculumProfile(
        code=f"pilot-math-{uuid4()}",
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
        code=f"MATH-G5-{uuid4()}",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    objective_revision = CurriculumObjectiveRevision(
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
    session.add_all([actor, objective_revision])
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=actor.id,
        curriculum_profile_id=profile.id,
        curriculum_objective_revision_id=objective_revision.id,
        grade="Grade 5",
        subject="mathematics",
        distribution_json={"question_types": ["M1"]},
        idempotency_key=str(uuid4()),
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
    )
    session.add(job)
    session.flush()
    attempt = GenerationAttempt(
        job_id=job.id,
        attempt_number=1,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        status="succeeded",
    )
    session.add(attempt)
    session.flush()
    candidate = {
        "objective_revision_id": str(objective_revision.id),
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "What is 2 + 2?",
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the two whole numbers.",
        "knowledge_point": "whole-number addition",
        "difficulty": 0.2,
    }
    draft = GeneratedQuestionDraft(
        job_id=job.id,
        generation_attempt_id=attempt.id,
        ordinal=1,
        content_hash="1" * 64,
        candidate_json=candidate,
        teacher_state="pending_review",
    )
    session.add(draft)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=draft.current_revision_id,
            generated_question_draft_id=draft.id,
            revision_number=1,
            candidate_json=candidate,
            content_hash=draft.content_hash,
        )
    )
    session.flush()
    return draft, actor


def _add_validation_run(
    session: Session,
    draft: GeneratedQuestionDraft,
    status: ValidationRunStatus,
    *,
    revision_id: object | None = None,
) -> GenerationValidationRun:
    run_number = session.scalar(
        select(func.count(GenerationValidationRun.id)).where(
            GenerationValidationRun.generated_question_draft_id == draft.id
        )
    )
    run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        draft_revision_id=revision_id or draft.current_revision_id,
        generation_job_id=draft.job_id,
        run_number=(run_number or 0) + 1,
        validator_version="verification-test",
        ruleset_version="rules-test",
        status=status,
        feature_summary_json={},
    )
    session.add(run)
    session.flush()
    return run


def _replace_current_candidate(
    session: Session,
    draft: GeneratedQuestionDraft,
    candidate: dict[str, object],
) -> GeneratedQuestionDraftRevision:
    revision = session.get(GeneratedQuestionDraftRevision, draft.current_revision_id)
    assert revision is not None
    draft.candidate_json = candidate
    revision.candidate_json = candidate
    draft.content_hash = "e" * 64
    revision.content_hash = draft.content_hash
    session.flush()
    return revision


def test_create_revision_is_append_only_and_validates_the_new_revision(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    original_candidate = deepcopy(draft.candidate_json)
    edited = {**draft.candidate_json, "prompt": "What is 3 + 2?"}

    result = create_review_revision(session, draft, actor, 1, edited, PassingGrader())

    assert result.revision.revision_number == 2
    assert result.validation_run.draft_revision_id == result.revision.id
    assert result.validation_run.status is ValidationRunStatus.PASSED
    assert draft.current_revision_id == result.revision.id
    assert draft.candidate_json == original_candidate


def test_stale_revision_never_overwrites_newer_edit(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    payload = {**draft.candidate_json, "prompt": "What is 3 + 2?"}
    create_review_revision(session, draft, actor, 1, payload, PassingGrader())

    with pytest.raises(ReviewConflictError, match="review_revision_conflict"):
        create_review_revision(session, draft, actor, 1, payload, PassingGrader())


@pytest.mark.parametrize(
    "actor_kind",
    ["student", "same_tenant_other_teacher", "cross_tenant_teacher"],
)
def test_review_service_denies_unauthorized_actor_roles_and_ownership(
    session: Session,
    review_draft: tuple[GeneratedQuestionDraft, User],
    actor_kind: str,
) -> None:
    draft, owner = review_draft
    if actor_kind == "student":
        actor = User(
            tenant_id=owner.tenant_id,
            role=Role.STUDENT,
            oidc_issuer="https://issuer.example.test",
            oidc_subject=str(uuid4()),
            display_name="Student",
            school_id=f"student-{uuid4()}",
        )
    elif actor_kind == "same_tenant_other_teacher":
        actor = User(
            tenant_id=owner.tenant_id,
            role=Role.TEACHER,
            oidc_issuer="https://issuer.example.test",
            oidc_subject=str(uuid4()),
            display_name="Other teacher",
        )
    else:
        other_tenant = Tenant(slug=f"other-{uuid4()}", name="Other tenant")
        actor = User(
            tenant=other_tenant,
            role=Role.TEACHER,
            oidc_issuer="https://issuer.example.test",
            oidc_subject=str(uuid4()),
            display_name="Cross-tenant teacher",
        )
    session.add(actor)
    session.flush()

    with pytest.raises(ReviewAccessError, match="review_access_denied"):
        create_review_revision(
            session,
            draft,
            actor,
            1,
            {**draft.candidate_json, "prompt": "Unauthorized edit"},
            PassingGrader(),
        )

    assert len(draft.revisions) == 1


@pytest.mark.parametrize("field", ["objective_revision_id", "question_type", "policy_version"])
def test_revision_cannot_change_candidate_identity(
    session: Session,
    review_draft: tuple[GeneratedQuestionDraft, User],
    field: str,
) -> None:
    draft, actor = review_draft
    payload = deepcopy(draft.candidate_json)
    payload[field] = str(uuid4()) if field == "objective_revision_id" else "E1"

    with pytest.raises(ReviewStateError, match="candidate_identity_changed"):
        create_review_revision(session, draft, actor, 1, payload, PassingGrader())

    assert len(draft.revisions) == 1


def test_blocked_revision_cannot_be_accepted(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    _add_validation_run(session, draft, ValidationRunStatus.BLOCKED)

    with pytest.raises(ReviewStateError, match="validation_blocked"):
        accept_review_draft(session, draft, actor, 1, confirm_warnings=False)

    assert session.scalar(select(func.count(QuestionVersion.id))) == 0


def test_warning_confirmation_creates_exactly_one_draft(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    run = _add_validation_run(session, draft, ValidationRunStatus.WARNING)

    with pytest.raises(ReviewStateError, match="warning_confirmation_required"):
        accept_review_draft(session, draft, actor, 1, confirm_warnings=False)

    result = accept_review_draft(session, draft, actor, 1, confirm_warnings=True)

    assert result.question_version.status is VersionStatus.DRAFT
    assert result.question_version.question.title == "AI M1 candidate 1"
    assert result.decision.accepted_question_version_id == result.question_version.id
    assert result.decision.generation_validation_run_id == run.id
    assert draft.teacher_state == "accepted"
    assert session.scalar(select(func.count(QuestionVersion.id))) == 1
    assert session.scalar(select(func.count(QuestionTestRun.id))) == 0
    with pytest.raises(ReviewConflictError, match="review_state_conflict"):
        accept_review_draft(session, draft, actor, 1, confirm_warnings=True)
    assert session.scalar(select(func.count(QuestionVersion.id))) == 1


def test_accept_preserves_non_e4_prompt_byte_for_byte(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    prompt = "  What is 2 + 2?\n"
    _replace_current_candidate(session, draft, {**draft.candidate_json, "prompt": prompt})
    _add_validation_run(session, draft, ValidationRunStatus.PASSED)

    result = accept_review_draft(session, draft, actor, 1, confirm_warnings=False)

    assert result.question_version.prompt == prompt


def test_accept_e4_projects_reading_material_into_question_version_and_visible_payload(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    objective_revision_id = draft.candidate_json["objective_revision_id"]
    candidate = {
        "objective_revision_id": objective_revision_id,
        "question_type": "E4",
        "policy_version": "2",
        "prompt": "  Why did the students arrive late?  ",
        "reading_material": "  Because the bridge was closed, the students arrived late.\n  ",
        "rule_json": {
            "scoring_points": [
                {
                    "id": "cause",
                    "evidence_phrases": ["because the bridge was closed"],
                    "score": 1,
                }
            ],
            "max_score": 1,
        },
        "explanation": "Identify the cause from the passage.",
        "knowledge_point": "reading comprehension",
        "difficulty": 0.4,
    }
    source_revision = _replace_current_candidate(session, draft, candidate)
    _add_validation_run(session, draft, ValidationRunStatus.PASSED)

    result = accept_review_draft(session, draft, actor, 1, confirm_warnings=False)
    expected_prompt = (
        "Because the bridge was closed, the students arrived late."
        "\n\nWhy did the students arrive late?"
    )
    visible = list_question_versions_route(
        CurrentPrincipal(
            user_id=str(actor.id),
            tenant_id=str(actor.tenant_id),
            role=Role.TEACHER,
            school_id=None,
            display_name=actor.display_name,
        ),
        session,
        query=None,
        question_type="E4",
        status=VersionStatus.DRAFT,
    )

    assert result.question_version.prompt == expected_prompt
    assert visible["question_versions"][0]["prompt"] == expected_prompt
    assert result.decision.draft_revision_id == source_revision.id


def test_accept_requires_a_latest_run_for_the_current_revision(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    old_revision_id = draft.current_revision_id
    old_run = _add_validation_run(session, draft, ValidationRunStatus.PASSED)
    edited = GeneratedQuestionDraftRevision(
        generated_question_draft_id=draft.id,
        revision_number=2,
        candidate_json={**draft.candidate_json, "prompt": "What is 3 + 2?"},
        content_hash="2" * 64,
    )
    session.add(edited)
    session.flush()
    draft.current_revision_id = edited.id
    session.flush()

    with pytest.raises(ReviewStateError, match="validation_stale"):
        accept_review_draft(session, draft, actor, 2, confirm_warnings=False)

    assert old_run.draft_revision_id == old_revision_id


def test_reject_creates_missing_validation_evidence_even_when_it_is_blocked(
    session: Session,
    review_draft: tuple[GeneratedQuestionDraft, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft, actor = review_draft

    class FailingDefaultGrader(PassingGrader):
        def grade(self, *args: object, **kwargs: object) -> GradeResult:
            raise RuntimeError("private diagnostic")

    monkeypatch.setattr(
        "edu_grader_api.services.ai_question_review._default_grader_client",
        FailingDefaultGrader,
    )

    decision = reject_review_draft(session, draft, actor, 1, "duplicate", None)

    assert decision.action == "reject"
    assert decision.validation_run.status is ValidationRunStatus.BLOCKED
    assert decision.draft_revision_id == draft.current_revision_id
    assert draft.teacher_state == "rejected"


@pytest.mark.parametrize(
    ("reason", "detail", "error"),
    [
        ("not_fixed", None, "invalid_rejection_reason"),
        ("other", None, "rejection_detail_required"),
        ("other", "", "rejection_detail_required"),
        ("other", "x" * 501, "rejection_detail_required"),
    ],
)
def test_reject_enforces_fixed_reason_contract(
    session: Session,
    review_draft: tuple[GeneratedQuestionDraft, User],
    reason: str,
    detail: str | None,
    error: str,
) -> None:
    draft, actor = review_draft
    _add_validation_run(session, draft, ValidationRunStatus.PASSED)

    with pytest.raises(ReviewStateError, match=error):
        reject_review_draft(session, draft, actor, 1, reason, detail)


def test_accept_persists_review_audit_without_candidate_content(
    session: Session, review_draft: tuple[GeneratedQuestionDraft, User]
) -> None:
    draft, actor = review_draft
    _add_validation_run(session, draft, ValidationRunStatus.PASSED)

    result = accept_review_draft(session, draft, actor, 1, confirm_warnings=False)

    review_event = session.scalar(
        select(AuditLog).where(AuditLog.event_type == "ai_question_review.accepted")
    )
    assert review_event is not None
    assert review_event.target_id == draft.id
    assert set(review_event.metadata_json) == {
        "revision_number",
        "validation_run_id",
        "question_version_id",
    }
    assert draft.candidate_json["prompt"] not in str(review_event.metadata_json)
    assert result.decision.actor_user_id == actor.id
    assert session.scalar(select(func.count(GeneratedQuestionReviewDecision.id))) == 1
