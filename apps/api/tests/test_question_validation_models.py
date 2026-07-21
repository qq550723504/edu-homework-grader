from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api import models
from edu_grader_api.models import (
    Base,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    GeneratedQuestionDraft,
    Role,
    Tenant,
    User,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_validation_models_are_draft_scoped_and_append_only() -> None:
    assert "generation_validation_runs" in Base.metadata.tables
    assert "validation_findings" in Base.metadata.tables

    runs = Base.metadata.tables["generation_validation_runs"]
    findings = Base.metadata.tables["validation_findings"]

    assert "question_version_id" not in runs.c
    assert "question_version_id" not in findings.c
    assert {"generated_question_draft_id", "generation_job_id", "run_number"} <= set(runs.c.keys())
    assert {"validation_run_id", "code", "severity", "evidence_json", "remediation"} <= set(
        findings.c.keys()
    )
    assert any(
        constraint.name == "uq_generation_validation_run_draft_number"
        for constraint in runs.constraints
    )


def test_validation_runs_keep_findings_for_each_draft_rerun(session: Session) -> None:
    assert hasattr(models, "GenerationValidationRun")
    assert hasattr(models, "ValidationFinding")

    validation_run_type = models.GenerationValidationRun
    validation_finding_type = models.ValidationFinding
    status_type = models.ValidationRunStatus
    severity_type = models.ValidationFindingSeverity

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
        idempotency_key="validation-runs",
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
    draft = GeneratedQuestionDraft(
        job_id=job.id,
        generation_attempt_id=attempt.id,
        ordinal=1,
        content_hash="b" * 64,
        candidate_json={"question_type": "M1", "prompt": "What is 2 + 2?"},
        teacher_state="pending_review",
    )
    session.add(draft)
    session.flush()

    first = validation_run_type(
        generated_question_draft_id=draft.id,
        generation_job_id=job.id,
        run_number=1,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=status_type.PASSED,
        feature_summary_json={"finding_count": 0},
    )
    second = validation_run_type(
        generated_question_draft_id=draft.id,
        generation_job_id=job.id,
        run_number=2,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=status_type.WARNING,
        feature_summary_json={"finding_count": 1},
    )
    finding = validation_finding_type(
        validation_run=second,
        code="duplicate_candidate_content",
        severity=severity_type.WARNING,
        evidence_json={"comparison": "normalized_prompt"},
        remediation="Revise the prompt before acceptance.",
    )
    session.add_all([first, second, finding])
    session.commit()

    assert draft.validation_runs == [first, second]
    assert second.findings == [finding]

    duplicate_run = validation_run_type(
        generated_question_draft_id=draft.id,
        generation_job_id=job.id,
        run_number=2,
        validator_version="verification-v1",
        ruleset_version="rules-v1",
        status=status_type.PASSED,
        feature_summary_json={},
    )
    session.add(duplicate_run)
    with pytest.raises(IntegrityError):
        session.commit()
