from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    GeneratedQuestionDraft,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.question_fingerprints import fingerprint_prompt


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


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
    first = GenerationJob(
        tenant=tenant,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=uuid4(),
        idempotency_key="same-request",
        status=GenerationJobStatus.QUEUED,
        requested_count=1,
    )
    second = GenerationJob(
        tenant=tenant,
        teacher_user_id=teacher.id,
        curriculum_objective_revision_id=uuid4(),
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
        curriculum_objective_revision_id=uuid4(),
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
    session.commit()

    assert job.drafts == [draft]
    assert not hasattr(draft, "question_version_id")


def test_generated_draft_candidate_prompt_assignment_refreshes_persisted_fingerprints(
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
        curriculum_objective_revision_id=uuid4(),
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
        candidate_json={"question_type": "M1", "prompt": "What is 2 + 2?"},
        teacher_state="pending_review",
    )
    session.add(draft)
    session.commit()

    draft.candidate_json = {"question_type": "M1", "prompt": "  WHAT\tIS 2 + 2?  "}
    session.commit()
    session.expire_all()

    stored = session.get(GeneratedQuestionDraft, draft.id)
    assert stored is not None
    expected = fingerprint_prompt("  WHAT\tIS 2 + 2?  ")
    assert stored.fingerprint_version == expected.version
    assert stored.exact_prompt_hash == expected.exact_hash
    assert stored.normalized_prompt_hash == expected.normalized_hash
