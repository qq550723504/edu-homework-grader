from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

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
    GenerationAttempt,
    GenerationControlState,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    GenerationJob,
    GenerationJobStatus,
    GenerationValidationRun,
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    Tenant,
    User,
    ValidationRunStatus,
    VersionStatus,
)
from edu_grader_api.services import ai_evaluation, ai_evaluation_gate
from edu_grader_api.services.ai_evaluation_operational import (
    EvaluationExportManifest,
    EvaluationExportSpec,
    EvaluationVersionSelector,
    OperationalEvaluationSpec,
    compare_evaluation_records,
    export_evaluation_records,
    write_operational_artifacts,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection: object, _connection_record: object) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as database_session:
        yield database_session


def _curriculum(session: Session, *, subject: str = "mathematics"):
    source = CurriculumSourceRecord(
        issuer="Example Board",
        title="Pilot curriculum",
        canonical_url="https://curriculum.example.test/pilot",
        version_label="2026",
    )
    profile = CurriculumProfile(
        code="pilot-2026",
        name="Pilot 2026",
        jurisdiction="pilot",
        version_label="2026",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
    )
    grade = CurriculumGradeMapping(
        profile=profile,
        internal_level="G7",
        external_label="Grade 7",
        position=7,
        complexity_rules_json={},
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code=f"{subject.upper()}-G7-001",
        subject=subject,
        domain="core",
        knowledge_point="core practice",
        status=CurriculumProfileStatus.ACTIVE,
    )
    revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Use grade-appropriate core knowledge.",
        source_locator="section 1",
        allowed_question_types=["M1", "M2", "E1", "E2", "E3", "E4"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add(revision)
    session.flush()
    return profile, revision


def _tenant_and_teacher(session: Session):
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
    return tenant, teacher


def _accepted_edited_draft(session: Session):
    observed_at = datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
    tenant, teacher = _tenant_and_teacher(session)
    profile, objective_revision = _curriculum(session)
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_profile_id=profile.id,
        curriculum_objective_revision_id=objective_revision.id,
        grade="G7",
        subject="mathematics",
        distribution_json={
            "items": [
                {
                    "question_type": "M1",
                    "difficulty_band": "standard",
                    "target_difficulty": 0.5,
                }
            ]
        },
        requested_count=1,
        status=GenerationJobStatus.READY_FOR_REVIEW,
        idempotency_key="operational-export",
        policy_version="2026.07",
        prompt_version="generator-v3",
        request_digest="a" * 64,
        created_at=observed_at,
        updated_at=observed_at,
    )
    attempt = GenerationAttempt(
        job=job,
        attempt_number=1,
        provider_name="openai",
        model_version="gpt-5.6-terra",
        prompt_version="generator-v3",
        seed=17,
        status="succeeded",
        request_summary={"prompt_template": {"fingerprint": "f" * 64}},
        duration_ms=240,
        cost_usd=0.04,
        started_at=observed_at,
        finished_at=observed_at,
    )
    original_candidate = {
        "objective_revision_id": str(objective_revision.id),
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "Original sensitive candidate prompt.",
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the values. Final answer: 4",
        "knowledge_point": "addition",
        "difficulty": 0.5,
        "verification_assertions": {
            "final_answer_text": "4",
            "final_answer_mathjson": None,
            "declared_max_score": 1,
        },
        "reading_material": None,
    }
    draft = GeneratedQuestionDraft(
        job=job,
        generation_attempt=attempt,
        ordinal=1,
        content_hash="1" * 64,
        candidate_json=original_candidate,
        teacher_state="pending_review",
        created_at=observed_at,
        updated_at=observed_at,
    )
    session.add_all([job, attempt, draft])
    session.flush()
    first_revision = GeneratedQuestionDraftRevision(
        id=draft.current_revision_id,
        generated_question_draft_id=draft.id,
        revision_number=1,
        candidate_json=original_candidate,
        content_hash="1" * 64,
        created_at=observed_at,
    )
    session.add(first_revision)
    session.flush()

    edited_candidate = {**original_candidate, "prompt": "Edited private candidate prompt."}
    edited_revision = GeneratedQuestionDraftRevision(
        generated_question_draft_id=draft.id,
        revision_number=2,
        candidate_json=edited_candidate,
        content_hash="2" * 64,
        editor_user_id=teacher.id,
        idempotency_key="edit-1",
        request_digest="b" * 64,
        created_at=observed_at + timedelta(seconds=1),
    )
    session.add(edited_revision)
    session.flush()
    draft.current_revision_id = edited_revision.id
    draft.updated_at = observed_at + timedelta(seconds=1)
    validation_run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        draft_revision_id=edited_revision.id,
        generation_job_id=job.id,
        run_number=1,
        validator_version="verification-v5",
        ruleset_version="rules-v5",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={
            "finding_count": 0,
            "difficulty_signal": {
                "availability": "available",
                "version": "rule-based-difficulty-v1",
                "target": 0.5,
                "estimated": 0.5,
                "deviation": 0,
                "curriculum_range": {"min": 0, "max": 1},
                "features": [],
                "reason": None,
            },
        },
        created_at=observed_at + timedelta(seconds=2),
    )
    session.add(validation_run)
    session.flush()

    policy = GradingPolicy(question_type="M1", policy_version="1", json_schema={})
    question = Question(
        tenant=tenant,
        created_by_user_id=teacher.id,
        title="Accepted question",
        created_at=observed_at + timedelta(seconds=3),
        updated_at=observed_at + timedelta(seconds=3),
    )
    version = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt="Published question prompt.",
        reading_material=None,
        question_type="M1",
        grading_policy=policy,
        rule_json={"expected": 4, "tolerance": 0},
        created_by_user_id=teacher.id,
        created_at=observed_at + timedelta(seconds=3),
        published_by_user_id=teacher.id,
        published_at=observed_at + timedelta(seconds=4),
    )
    session.add_all([policy, question, version])
    session.flush()
    decision = GeneratedQuestionReviewDecision(
        generated_question_draft_id=draft.id,
        draft_revision_id=edited_revision.id,
        generation_validation_run_id=validation_run.id,
        action="accept",
        reason=None,
        warning_confirmed=False,
        actor_user_id=teacher.id,
        accepted_question_version_id=version.id,
        idempotency_key="accept-1",
        request_digest="c" * 64,
        created_at=observed_at + timedelta(seconds=3),
    )
    session.add(decision)
    draft.teacher_state = "accepted"
    session.commit()
    return tenant, draft, observed_at


def test_export_maps_final_review_revision_without_sensitive_content(session: Session) -> None:
    tenant, draft, observed_at = _accepted_edited_draft(session)
    exported = export_evaluation_records(
        session,
        EvaluationExportSpec(
            tenant_id=tenant.id,
            run_id="production-export-1",
            watermark=observed_at + timedelta(minutes=1),
        ),
    )

    assert exported.issues == []
    assert exported.manifest.record_count == 1
    record = exported.records[0]
    assert record.record_id == f"{draft.id}:{draft.current_revision_id}"
    assert record.teacher_outcome == "accepted_after_edit"
    assert record.teacher_edited is True
    assert record.published is True
    assert record.review_evidence is True
    assert record.math_answer_correct is True
    assert record.cost_usd == pytest.approx(0.04)
    assert record.duration_ms == 240
    assert record.parameters["provider_name"] == "openai"
    assert record.parameters["prompt_template_fingerprint"] == "f" * 64
    serialized = record.model_dump_json()
    assert "Original sensitive candidate prompt" not in serialized
    assert "Edited private candidate prompt" not in serialized
    assert "teacher@example.test" not in serialized
    assert exported.manifest.record_digest
    assert exported.manifest.source_counts == {"accepted_after_edit": 1}


def test_export_fails_closed_when_validation_evidence_is_missing(session: Session) -> None:
    tenant, teacher = _tenant_and_teacher(session)
    profile, objective_revision = _curriculum(session)
    observed_at = datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc)
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_profile_id=profile.id,
        curriculum_objective_revision_id=objective_revision.id,
        grade="G7",
        subject="mathematics",
        distribution_json={
            "items": [
                {
                    "question_type": "M1",
                    "difficulty_band": "standard",
                    "target_difficulty": 0.5,
                }
            ]
        },
        requested_count=1,
        status=GenerationJobStatus.READY_FOR_REVIEW,
        idempotency_key="missing-evidence",
        prompt_version="generator-v3",
        policy_version="2026.07",
        request_digest="d" * 64,
        created_at=observed_at,
        updated_at=observed_at,
    )
    attempt = GenerationAttempt(
        job=job,
        attempt_number=1,
        provider_name="openai",
        model_version="gpt-5.6-terra",
        prompt_version="generator-v3",
        status="succeeded",
        started_at=observed_at,
        finished_at=observed_at,
    )
    candidate = {
        "objective_revision_id": str(objective_revision.id),
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "Private prompt.",
        "rule_json": {"expected": 4},
        "explanation": "Final answer: 4",
        "knowledge_point": "addition",
        "difficulty": 0.5,
        "verification_assertions": {
            "final_answer_text": "4",
            "final_answer_mathjson": None,
            "declared_max_score": 1,
        },
        "reading_material": None,
    }
    draft = GeneratedQuestionDraft(
        job=job,
        generation_attempt=attempt,
        ordinal=1,
        content_hash="3" * 64,
        candidate_json=candidate,
        created_at=observed_at,
        updated_at=observed_at,
    )
    session.add_all([job, attempt, draft])
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=draft.current_revision_id,
            generated_question_draft_id=draft.id,
            revision_number=1,
            candidate_json=candidate,
            content_hash="3" * 64,
            created_at=observed_at,
        )
    )
    session.commit()

    exported = export_evaluation_records(
        session,
        EvaluationExportSpec(
            tenant_id=tenant.id,
            run_id="production-export-missing",
            watermark=observed_at + timedelta(minutes=1),
        ),
    )

    assert exported.records == []
    assert [issue.code for issue in exported.issues] == [
        "evaluation_export_evidence_missing"
    ]
    assert exported.manifest.issue_count == 1


def _gate_policy() -> ai_evaluation_gate.GatePolicy:
    return ai_evaluation_gate.GatePolicy.model_validate(
        {
            "policy_id": "operational-policy-v1",
            "approved_model_ids": ["gpt-5.6-terra", "gpt-5.6-sol"],
            "approved_prompt_versions": ["generator-v3"],
            "thresholds": {
                "schema_pass_rate_min": 0,
                "math_answer_error_rate_max": 1,
                "grade_mismatch_rate_max": 1,
                "duplicate_or_similarity_rate_max": 1,
                "teacher_direct_accept_rate_min": 0,
                "teacher_modified_accept_rate_min": 0,
                "published_without_teacher_review_max": 1,
            },
            "evidence_requirements": {
                "required_question_types": ["M1", "M2", "E1", "E2", "E3", "E4"],
                "minimum_total_records": 6,
                "minimum_records_per_question_type": 1,
                "minimum_reviewed_records_per_question_type": 1,
            },
        }
    )


def _selector(model_id: str) -> EvaluationVersionSelector:
    return EvaluationVersionSelector(
        provider_name="openai",
        model_id=model_id,
        prompt_version="generator-v3",
        validator_version="verification-v5",
    )


def _comparison_spec(tenant_id) -> OperationalEvaluationSpec:
    return OperationalEvaluationSpec(
        spec_id="operational-comparison-v1",
        export=EvaluationExportSpec(
            tenant_id=tenant_id,
            run_id="operational-run-v1",
            watermark=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        ),
        baseline=_selector("gpt-5.6-terra"),
        candidate=_selector("gpt-5.6-sol"),
        gate_policy=_gate_policy(),
        max_metric_regression={
            metric: 0
            for metric in (
                "schema_pass_rate",
                "math_answer_error_rate",
                "grade_mismatch_rate",
                "duplicate_or_similarity_rate",
                "teacher_direct_accept_rate",
                "teacher_modified_accept_rate",
                "published_without_teacher_review",
            )
        },
    )


def _records_for_version(model_id: str, *, candidate_regression: bool = False):
    records = []
    for index, question_type in enumerate(("M1", "M2", "E1", "E2", "E3", "E4")):
        records.append(
            ai_evaluation.EvaluationRecord(
                record_id=f"{model_id}-{question_type}",
                run_id="operational-run-v1",
                curriculum_profile="pilot-2026",
                grade="G7",
                subject="mathematics" if question_type.startswith("M") else "english",
                question_type=question_type,
                model_id=model_id,
                prompt_version="generator-v3",
                validator_version="verification-v5",
                difficulty_band="standard",
                seed=index,
                parameters={"provider_name": "openai"},
                content_fingerprint=(
                    f"{model_id}-{question_type}".encode().hex()[:64].ljust(64, "0")
                ),
                schema_valid=True,
                math_answer_correct=True if question_type.startswith("M") else None,
                grade_aligned=not (candidate_regression and question_type == "M1"),
                duplicate_exact=False,
                similarity_high=False,
                teacher_outcome="accepted_directly",
                teacher_edited=False,
                rejection_category=None,
                published=True,
                review_evidence=True,
                cost_usd=0.01,
                duration_ms=100,
            )
        )
    return records


def _active_governance(session: Session, selectors) -> None:
    entries = [
        GenerationGovernanceEntry(
            is_global=True,
            tenant_id=None,
            target_type=GenerationGovernanceTargetType.PROVIDER,
            target_key="openai",
            control_state=GenerationControlState.ACTIVE,
        ),
        GenerationGovernanceEntry(
            is_global=True,
            tenant_id=None,
            target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
            target_key="generator-v3",
            control_state=GenerationControlState.ACTIVE,
        ),
    ]
    for selector in selectors:
        entries.append(
            GenerationGovernanceEntry(
                is_global=True,
                tenant_id=None,
                target_type=GenerationGovernanceTargetType.MODEL,
                target_key=selector.model_id,
                control_state=GenerationControlState.ACTIVE,
            )
        )
    session.add_all(entries)
    session.flush()


def _manifest(tenant_id) -> EvaluationExportManifest:
    return EvaluationExportManifest(
        exporter_version="operational-ai-evaluation-export-v1",
        run_id="operational-run-v1",
        tenant_id=str(tenant_id),
        watermark=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc),
        record_count=12,
        issue_count=0,
        record_digest="e" * 64,
        source_counts={"accepted_directly": 12},
    )


def test_explicit_version_comparison_blocks_candidate_regression(session: Session) -> None:
    tenant, _teacher = _tenant_and_teacher(session)
    spec = _comparison_spec(tenant.id)
    _active_governance(session, (spec.baseline, spec.candidate))
    records = [
        *_records_for_version("gpt-5.6-terra"),
        *_records_for_version("gpt-5.6-sol", candidate_regression=True),
    ]

    report = compare_evaluation_records(
        session,
        records=records,
        spec=spec,
        manifest=_manifest(tenant.id),
    )

    assert report.baseline_gate is not None and report.baseline_gate.promotion_eligible is True
    assert report.candidate_gate is not None and report.candidate_gate.promotion_eligible is True
    assert report.promotion_eligible is False
    assert "evaluation_candidate_regression" in {
        violation.code for violation in report.violations
    }
    assert report.metric_comparisons["grade_mismatch_rate"].state == "fail"
    assert any(
        comparison["key"].get("question_type") == "M1"
        and comparison["metrics"]["grade_mismatch_rate"]["state"] == "fail"
        for comparison in report.strata
    )


def test_comparison_fails_closed_without_explicit_governance_approval(session: Session) -> None:
    tenant, _teacher = _tenant_and_teacher(session)
    spec = _comparison_spec(tenant.id)
    records = [
        *_records_for_version("gpt-5.6-terra"),
        *_records_for_version("gpt-5.6-sol"),
    ]

    report = compare_evaluation_records(
        session,
        records=records,
        spec=spec,
        manifest=_manifest(tenant.id),
    )

    assert report.promotion_eligible is False
    governance_violations = [
        violation
        for violation in report.violations
        if violation.code == "evaluation_governance_approval_missing"
    ]
    assert len(governance_violations) == 6
    assert {violation.key["role"] for violation in governance_violations} == {
        "baseline",
        "candidate",
    }


def test_write_operational_artifacts_never_serializes_candidate_content(
    session: Session, tmp_path: Path
) -> None:
    tenant, _draft, observed_at = _accepted_edited_draft(session)
    exported = export_evaluation_records(
        session,
        EvaluationExportSpec(
            tenant_id=tenant.id,
            run_id="artifact-run",
            watermark=observed_at + timedelta(minutes=1),
        ),
    )
    report = compare_evaluation_records(
        session,
        records=exported.records,
        spec=_comparison_spec(tenant.id),
        manifest=exported.manifest,
    )
    write_operational_artifacts(exported, report, tmp_path)

    artifact_names = (
        "records.jsonl",
        "manifest.json",
        "export-issues.json",
        "report.json",
        "report.html",
    )
    for filename in artifact_names:
        assert (tmp_path / filename).is_file()
    all_content = "\n".join(
        (tmp_path / filename).read_text(encoding="utf-8") for filename in artifact_names
    )
    assert "Original sensitive candidate prompt" not in all_content
    assert "Edited private candidate prompt" not in all_content
    assert "teacher@example.test" not in all_content
