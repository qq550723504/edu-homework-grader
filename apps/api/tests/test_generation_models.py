from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_generator.contracts import GeneratedCandidate
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
    GeneratedQuestionReviewDecision,
    GenerationValidationRun,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    Role,
    Tenant,
    User,
    ValidationRunStatus,
)
from edu_grader_api.services.generation import _persist_valid_candidates
from edu_grader_api.services.question_fingerprints import fingerprint_prompt


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def active_objective_revision_id(session: Session):
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
    session.add(revision)
    session.flush()
    return revision.id


def persist_generated_draft(
    session: Session,
    *,
    job_idempotency_key: str = "initial-review-revision",
    tenant: Tenant | None = None,
    teacher: User | None = None,
    objective_revision_id: object | None = None,
) -> GeneratedQuestionDraft:
    if teacher is None:
        tenant = Tenant(slug="pilot", name="Pilot")
        teacher = User(
            tenant=tenant,
            role=Role.TEACHER,
            oidc_issuer="https://issuer.example.test",
            oidc_subject="teacher-subject",
            display_name="Teacher",
            work_email="teacher@example.test",
        )
        session.add(teacher)
        session.flush()
        objective_revision_id = active_objective_revision_id(session)
    assert tenant is not None
    assert objective_revision_id is not None
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=objective_revision_id,
        distribution_json={
            "items": [
                {
                    "question_type": "M1",
                    "difficulty_band": "standard",
                    "target_difficulty": 0.5,
                }
            ]
        },
        idempotency_key=job_idempotency_key,
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
    )
    attempt = GenerationAttempt(
        job=job,
        attempt_number=1,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        status="succeeded",
    )
    session.add_all([job, attempt])
    session.flush()

    created = _persist_valid_candidates(
        session,
        job=job,
        attempt=attempt,
        candidates=[
            GeneratedCandidate(
                objective_revision_id=job.curriculum_objective_revision_id,
                question_type="M1",
                policy_version="1",
                prompt="What is 2 + 2?",
                rule_json={"expected": 4},
                explanation="Add the two numbers.",
                knowledge_point="addition",
                difficulty=0.5,
            )
        ],
    )
    assert created == 1
    session.flush()
    return job.drafts[0]


def append_initial_revision(
    session: Session, draft: GeneratedQuestionDraft
) -> GeneratedQuestionDraftRevision:
    session.flush()
    revision = GeneratedQuestionDraftRevision(
        id=draft.current_revision_id,
        generated_question_draft_id=draft.id,
        revision_number=1,
        candidate_json=draft.candidate_json,
        content_hash=draft.content_hash,
    )
    session.add(revision)
    session.flush()
    return revision


def test_generated_draft_creates_an_immutable_initial_review_revision(session: Session) -> None:
    draft = persist_generated_draft(session)

    assert draft.current_revision.revision_number == 1
    assert draft.current_revision.candidate_json == draft.candidate_json
    assert draft.current_revision.content_hash == draft.content_hash
    assert draft.current_revision.idempotency_key is None
    assert draft.current_revision.request_digest is None


def test_validation_run_references_the_review_revision(session: Session) -> None:
    draft = persist_generated_draft(session)
    run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        generation_job_id=draft.job_id,
        draft_revision_id=draft.current_revision_id,
        run_number=1,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={},
    )
    session.add(run)
    session.flush()

    assert run.draft_revision_id == run.draft.current_revision_id


def test_review_evidence_rows_require_matching_draft_revision_pairs(session: Session) -> None:
    first_draft = persist_generated_draft(session, job_idempotency_key="first-draft")
    second_draft = persist_generated_draft(
        session,
        job_idempotency_key="second-draft",
        tenant=first_draft.job.tenant,
        teacher=first_draft.job.teacher,
        objective_revision_id=first_draft.job.curriculum_objective_revision_id,
    )

    unrelated_revision_run = GenerationValidationRun(
        generated_question_draft_id=second_draft.id,
        generation_job_id=second_draft.job_id,
        draft_revision_id=first_draft.current_revision_id,
        run_number=1,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={},
    )
    session.add(unrelated_revision_run)

    with pytest.raises(IntegrityError):
        session.flush()


def test_review_decision_requires_matching_validation_evidence(session: Session) -> None:
    assert GeneratedQuestionReviewDecision.__table__.c.idempotency_key.nullable is False
    assert GeneratedQuestionReviewDecision.__table__.c.request_digest.nullable is False

    first_draft = persist_generated_draft(session, job_idempotency_key="decision-first")
    second_draft = persist_generated_draft(
        session,
        job_idempotency_key="decision-second",
        tenant=first_draft.job.tenant,
        teacher=first_draft.job.teacher,
        objective_revision_id=first_draft.job.curriculum_objective_revision_id,
    )
    validation_run = GenerationValidationRun(
        generated_question_draft_id=first_draft.id,
        generation_job_id=first_draft.job_id,
        draft_revision_id=first_draft.current_revision_id,
        run_number=1,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={},
    )
    session.add(validation_run)
    session.flush()
    decision = GeneratedQuestionReviewDecision(
        generated_question_draft_id=second_draft.id,
        draft_revision_id=first_draft.current_revision_id,
        generation_validation_run_id=validation_run.id,
        action="accept",
        warning_confirmed=False,
        actor_user_id=first_draft.job.teacher_user_id,
        idempotency_key="review-decision-1",
        request_digest="a" * 64,
    )
    session.add(decision)

    with pytest.raises(IntegrityError):
        session.flush()


def test_ai_review_migration_installs_append_only_postgresql_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0019_ai_generated_question_reviews.py"
    )
    spec = spec_from_file_location("migration_0019_ai_reviews", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._install_append_only_evidence_triggers()

    assert len(statements) == 1
    for table_name in (
        "generated_question_draft_revisions",
        "generated_question_review_decisions",
        "generation_validation_runs",
    ):
        assert f"BEFORE UPDATE OR DELETE ON {table_name}" in statements[0]


def test_review_evidence_protection_migration_scopes_postgresql_triggers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration_path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0021_protect_ai_review_evidence.py"
    )
    spec = spec_from_file_location("migration_0021_review_protection", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
    )
    monkeypatch.setattr(migration.op, "execute", statements.append)

    migration._install_review_evidence_protection_triggers()

    assert migration.down_revision == "0020_question_version_reading_material"
    assert len(statements) == 1
    sql = statements[0]
    assert "BEFORE UPDATE OF candidate_json ON generated_question_drafts" in sql
    assert "WHEN (OLD.candidate_json::jsonb IS DISTINCT FROM NEW.candidate_json::jsonb)" in sql
    assert "BEFORE UPDATE OR DELETE ON generated_question_drafts" not in sql
    assert "BEFORE UPDATE OR DELETE ON validation_findings" in sql


def test_generation_job_is_unique_per_tenant_idempotency_key(session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    session.add(teacher)
    session.flush()
    objective_revision_id = active_objective_revision_id(session)
    first = GenerationJob(
        tenant=tenant,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=objective_revision_id,
        idempotency_key="same-request",
        status=GenerationJobStatus.QUEUED,
        requested_count=1,
    )
    second = GenerationJob(
        tenant=tenant,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=objective_revision_id,
        idempotency_key="same-request",
        status=GenerationJobStatus.QUEUED,
        requested_count=1,
    )
    session.add_all([first, second])

    with pytest.raises(IntegrityError):
        session.commit()


def test_generation_drafts_are_scoped_to_a_job_and_attempt(session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    session.add(teacher)
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=active_objective_revision_id(session),
        idempotency_key="draft-scope",
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
    )
    session.add(job)
    session.flush()

    from edu_grader_api.models import GeneratedQuestionDraft, GenerationAttempt

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
    draft = GeneratedQuestionDraft(
        job_id=job.id,
        generation_attempt_id=attempt.id,
        ordinal=1,
        content_hash="a" * 64,
        candidate_json={"question_type": "M1", "prompt": "What is 2 + 2?"},
        teacher_state="pending_review",
    )
    session.add(draft)
    append_initial_revision(session, draft)
    session.commit()

    assert job.drafts == [draft]
    assert not hasattr(draft, "question_version_id")


def test_generated_draft_initial_candidate_prompt_sets_persisted_fingerprints(
    session: Session,
) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    session.add(teacher)
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=active_objective_revision_id(session),
        idempotency_key="fingerprint-draft",
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
    )
    attempt = GenerationAttempt(
        job=job,
        attempt_number=1,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        status="succeeded",
    )
    draft = GeneratedQuestionDraft(
        job=job,
        generation_attempt=attempt,
        ordinal=1,
        content_hash="b" * 64,
        candidate_json={"question_type": "M1", "prompt": "  WHAT\tIS 2 + 2?  "},
        teacher_state="pending_review",
    )
    session.add(draft)
    append_initial_revision(session, draft)
    session.commit()

    session.expire_all()

    stored = session.get(GeneratedQuestionDraft, draft.id)
    assert stored is not None
    expected = fingerprint_prompt("  WHAT\tIS 2 + 2?  ")
    assert stored.fingerprint_version == expected.version
    assert stored.exact_prompt_hash == expected.exact_hash
    assert stored.normalized_prompt_hash == expected.normalized_hash


@pytest.mark.parametrize(
    "malformed_candidate_json",
    [
        {"question_type": "M1"},
        {"question_type": "M1", "prompt": 2},
    ],
)
def test_generated_draft_malformed_initial_candidate_uses_empty_prompt_fingerprints(
    session: Session, malformed_candidate_json: dict[str, object]
) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="teacher-subject",
        display_name="Teacher",
        work_email="teacher@example.test",
    )
    session.add(teacher)
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=active_objective_revision_id(session),
        idempotency_key="malformed-fingerprint-draft",
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
    )
    attempt = GenerationAttempt(
        job=job,
        attempt_number=1,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        status="succeeded",
    )
    draft = GeneratedQuestionDraft(
        job=job,
        generation_attempt=attempt,
        ordinal=1,
        content_hash="c" * 64,
        candidate_json=malformed_candidate_json,
        teacher_state="pending_review",
    )
    session.add(draft)
    append_initial_revision(session, draft)
    session.commit()

    session.expire_all()

    stored = session.get(GeneratedQuestionDraft, draft.id)
    assert stored is not None
    expected = fingerprint_prompt("")
    assert stored.fingerprint_version == expected.version
    assert stored.exact_prompt_hash == expected.exact_hash
    assert stored.normalized_prompt_hash == expected.normalized_hash
