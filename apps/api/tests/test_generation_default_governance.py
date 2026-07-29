from datetime import UTC, datetime
from importlib import import_module
from importlib.util import find_spec

import pytest
from edu_generator.prompt_templates import resolve_prompt_template
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    GenerationControlState,
    GenerationDefaultChangeStatus,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.ai_evaluation_operational import (
    OperationalEvaluationReport,
    signed_operational_evaluation_evidence,
)
from edu_grader_api.settings import settings


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def platform_admin(session: Session, *, subject: str = "platform-admin") -> User:
    tenant = Tenant(slug=f"tenant-{subject}", name="Governance tenant")
    user = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer="https://issuer.example.test",
        oidc_subject=subject,
        display_name="Platform administrator",
        work_email=f"{subject}@example.test",
    )
    session.add(user)
    session.commit()
    return user


def passing_report(
    *,
    model_id: str = "fake-v1",
    provider_name: str = "fake",
    baseline_model_id: str = "fake-v0",
    baseline_provider_name: str = "fake",
) -> dict[str, object]:
    passing_gate = {
        "policy_id": "generation-default-governance-v1",
        "promotion_eligible": True,
        "metrics": {},
        "violations": [],
        "rejection_reason_counts": {},
        "cost_per_final_accepted_question": None,
        "end_to_end_duration_ms": {},
    }
    report = OperationalEvaluationReport(
        spec_id="generation-default-governance-v1",
        exporter_version="operational-export-v1",
        run_id="run-001",
        tenant_id="pilot",
        watermark=datetime(2026, 7, 28, tzinfo=UTC),
        baseline={
            "provider_name": baseline_provider_name,
            "model_id": baseline_model_id,
            "prompt_version": "generator-v1",
            "prompt_template_fingerprint": resolve_prompt_template(
                "generator-v1", ("M1", "M2", "E1", "E2", "E3", "E4")
            ).fingerprint,
            "validator_version": "verification-v1",
        },
        candidate={
            "provider_name": provider_name,
            "model_id": model_id,
            "prompt_version": "generator-v1",
            "prompt_template_fingerprint": resolve_prompt_template(
                "generator-v1", ("M1", "M2", "E1", "E2", "E3", "E4")
            ).fingerprint,
            "validator_version": "verification-v1",
        },
        promotion_eligible=True,
        export_manifest={
            "exporter_version": "operational-export-v1",
            "run_id": "run-001",
            "tenant_id": "pilot",
            "watermark": datetime(2026, 7, 28, tzinfo=UTC),
            "record_count": 12,
            "issue_count": 0,
            "record_digest": "a" * 64,
            "source_counts": {"accepted_directly": 12},
        },
        baseline_gate=passing_gate,
        candidate_gate=passing_gate,
    )
    return signed_operational_evaluation_evidence(
        report, hmac_key=settings.evaluation_evidence_hmac_key
    )


def signed_report(report: dict[str, object]) -> dict[str, object]:
    return signed_operational_evaluation_evidence(
        OperationalEvaluationReport.model_validate(report),
        hmac_key=settings.evaluation_evidence_hmac_key,
    )


def governance_service():
    assert find_spec("edu_grader_api.services.generation_default_governance") is not None
    return import_module("edu_grader_api.services.generation_default_governance")


def test_submit_rejects_unsigned_evaluation_evidence(session: Session) -> None:
    service = governance_service()
    unsigned_report = {"report": passing_report()["report"], "signature": "0" * 64}

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=platform_admin(session),
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote evidence that was not produced by the protected evaluator",
            evaluation_report=unsigned_report,
            idempotency_key="unsigned-evidence",
        )

    assert error.value.code == "evaluation_evidence_untrusted"


def test_submit_rejects_evaluation_for_a_different_candidate(
    session: Session,
) -> None:
    service = governance_service()
    admin = platform_admin(session)

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote verified candidate",
            evaluation_report=passing_report(model_id="fake-v2"),
            idempotency_key="promote-1",
        )

    assert error.value.code == "evaluation_candidate_mismatch"


def test_submit_replays_before_rechecking_mutable_provider_state(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = governance_service()
    actor = platform_admin(session)
    request = service.submit_change_request(
        session,
        actor=actor,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Promote verified candidate",
        evaluation_report=passing_report(),
        idempotency_key="submission-replay",
    )
    monkeypatch.setattr(service, "supports_generation_provider", lambda *_: False)

    replay = service.submit_change_request(
        session,
        actor=actor,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Promote verified candidate",
        evaluation_report=passing_report(),
        idempotency_key="submission-replay",
    )

    assert replay.id == request.id


def test_submit_rejects_provider_pair_missing_from_runtime_registry(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v2",
            prompt_version="generator-v1",
            request_reason="Promote unsupported candidate",
            evaluation_report=passing_report(model_id="fake-v2"),
            idempotency_key="unsupported-provider-pair",
        )

    assert error.value.code == "default_provider_not_configured"


def test_submit_rejects_promotion_flag_without_passing_gate_evidence(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)
    report = passing_report()["report"]
    report["candidate_gate"] = None

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote unverified candidate",
            evaluation_report=signed_report(report),
            idempotency_key="missing-gate-evidence",
        )

    assert error.value.code == "evaluation_not_promotion_eligible"


def test_submit_rejects_gate_that_claims_eligibility_despite_violations(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)
    report = passing_report()["report"]
    report["candidate_gate"]["violations"] = [
        {
            "code": "evaluation_threshold_failed",
            "metric": "acceptance_rate",
            "key": {"scope": "candidate"},
        }
    ]

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote contradictory report",
            evaluation_report=signed_report(report),
            idempotency_key="contradictory-gate-evidence",
        )

    assert error.value.code == "evaluation_not_promotion_eligible"


def test_submitter_cannot_approve_own_change_request(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)
    change_request = service.submit_change_request(
        session,
        actor=admin,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Promote verified candidate",
        evaluation_report=passing_report(),
        idempotency_key="promote-2",
    )

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.approve_change_request(
            session,
            request_id=change_request.id,
            actor=admin,
            approval_reason="Verified",
        )

    assert error.value.code == "default_change_self_approval_forbidden"


def test_apply_selects_new_default_and_supersedes_previous_request(session: Session) -> None:
    service = governance_service()
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    original = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Initial governed default",
        evaluation_report=passing_report(),
        idempotency_key="promote-3",
    )
    service.approve_change_request(
        session, request_id=original.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=original.id, actor=submitter, application_reason="Release"
    )
    replacement = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Upgrade governed default",
        evaluation_report=passing_report(baseline_model_id="fake-v1"),
        idempotency_key="promote-4",
    )
    service.approve_change_request(
        session, request_id=replacement.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=replacement.id, actor=submitter, application_reason="Release"
    )

    assert service.resolve_active_default(session).model_version == "fake-v1"
    assert original.status is GenerationDefaultChangeStatus.SUPERSEDED
    assert replacement.status is GenerationDefaultChangeStatus.APPLIED

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=submitter,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Use evidence against a different baseline",
            evaluation_report=passing_report(),
            idempotency_key="wrong-baseline",
        )

    assert error.value.code == "evaluation_baseline_mismatch"


def test_rollback_is_a_new_approved_change_request(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = governance_service()
    monkeypatch.setattr(service, "supports_generation_provider", lambda *_: True)
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    original = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Initial governed default",
        evaluation_report=passing_report(),
        idempotency_key="promote-5",
    )
    service.approve_change_request(
        session, request_id=original.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=original.id, actor=submitter, application_reason="Release"
    )
    replacement = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v2",
        prompt_version="generator-v1",
        request_reason="Upgrade governed default",
        evaluation_report=passing_report(model_id="fake-v2", baseline_model_id="fake-v1"),
        idempotency_key="promote-6",
    )
    service.approve_change_request(
        session, request_id=replacement.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=replacement.id, actor=submitter, application_reason="Release"
    )

    rollback = service.submit_rollback_request(
        session,
        actor=submitter,
        target_request_id=original.id,
        request_reason="Regression in replacement",
        idempotency_key="rollback-1",
    )
    original_scalar = session.scalar
    calls = 0

    def stale_first_lookup(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            return None
        return original_scalar(*args, **kwargs)

    monkeypatch.setattr(session, "scalar", stale_first_lookup)
    replay = service.submit_rollback_request(
        session,
        actor=submitter,
        target_request_id=original.id,
        request_reason="Regression in replacement",
        idempotency_key="rollback-1",
    )
    monkeypatch.setattr(session, "scalar", original_scalar)
    service.approve_change_request(
        session, request_id=rollback.id, actor=approver, approval_reason="Rollback verified"
    )
    service.apply_change_request(
        session, request_id=rollback.id, actor=submitter, application_reason="Rollback"
    )

    assert service.resolve_active_default(session).model_version == "fake-v1"
    assert replacement.status is GenerationDefaultChangeStatus.ROLLED_BACK
    assert rollback.status is GenerationDefaultChangeStatus.APPLIED
    assert replay.id == rollback.id

    restore = service.submit_rollback_request(
        session,
        actor=submitter,
        target_request_id=replacement.id,
        request_reason="Undo the rollback",
        idempotency_key="restore-replacement",
    )

    assert restore.configuration_id == replacement.configuration_id


def test_submit_rejects_globally_paused_candidate_component(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)
    session.add(
        GenerationGovernanceEntry(
            is_global=True,
            target_type=GenerationGovernanceTargetType.MODEL,
            target_key="fake-v1",
            control_state=GenerationControlState.PAUSED,
            created_by_user_id=admin.id,
        )
    )
    session.commit()

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote paused candidate",
            evaluation_report=passing_report(),
            idempotency_key="promote-paused",
        )

    assert error.value.code == "default_component_not_active"


def test_rejected_change_request_cannot_be_applied(session: Session) -> None:
    service = governance_service()
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    change_request = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Candidate no longer needed",
        evaluation_report=passing_report(),
        idempotency_key="promote-reject",
    )

    service.reject_change_request(
        session, request_id=change_request.id, actor=approver, rejection_reason="Cancelled"
    )

    assert change_request.status is GenerationDefaultChangeStatus.REJECTED
    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.apply_change_request(
            session, request_id=change_request.id, actor=submitter, application_reason="Release"
        )
    assert error.value.code == "default_change_not_approved"


def test_apply_rechecks_governance_controls(session: Session) -> None:
    service = governance_service()
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    change_request = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Promote verified candidate",
        evaluation_report=passing_report(),
        idempotency_key="promote-control-recheck",
    )
    service.approve_change_request(
        session, request_id=change_request.id, actor=approver, approval_reason="Verified"
    )
    session.add(
        GenerationGovernanceEntry(
            is_global=True,
            target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
            target_key="generator-v1",
            control_state=GenerationControlState.PAUSED,
            created_by_user_id=approver.id,
        )
    )
    session.commit()

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.apply_change_request(
            session, request_id=change_request.id, actor=submitter, application_reason="Release"
        )

    assert error.value.code == "default_component_not_active"


def test_submit_binds_evidence_to_the_resolved_prompt_fingerprint(session: Session) -> None:
    service = governance_service()
    report = passing_report()["report"]
    report["candidate"]["prompt_template_fingerprint"] = "0" * 64

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=platform_admin(session),
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote stale evidence",
            evaluation_report=signed_report(report),
            idempotency_key="stale-evidence",
        )

    assert error.value.code == "evaluation_prompt_template_mismatch"


def test_approval_is_timestamped_and_exact_retries_are_replayed(session: Session) -> None:
    service = governance_service()
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    change_request = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Promote verified candidate",
        evaluation_report=passing_report(),
        idempotency_key="approval-retry-request",
    )

    approved = service.approve_change_request(
        session,
        request_id=change_request.id,
        actor=approver,
        approval_reason="Verified",
        idempotency_key="approval-retry",
    )
    replay = service.approve_change_request(
        session,
        request_id=change_request.id,
        actor=approver,
        approval_reason="Verified",
        idempotency_key="approval-retry",
    )
    service.apply_change_request(
        session,
        request_id=change_request.id,
        actor=submitter,
        application_reason="Release",
        idempotency_key="apply-retry",
    )
    after_apply_replay = service.approve_change_request(
        session,
        request_id=change_request.id,
        actor=approver,
        approval_reason="Verified",
        idempotency_key="approval-retry",
    )
    replacement = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Supersede the previous default",
        evaluation_report=passing_report(baseline_model_id="fake-v1"),
        idempotency_key="superseding-request",
    )
    service.approve_change_request(
        session,
        request_id=replacement.id,
        actor=approver,
        approval_reason="Verified replacement",
    )
    service.apply_change_request(
        session,
        request_id=replacement.id,
        actor=submitter,
        application_reason="Release replacement",
    )
    after_supersession_replay = service.apply_change_request(
        session,
        request_id=change_request.id,
        actor=submitter,
        application_reason="Release",
        idempotency_key="apply-retry",
    )

    assert approved.approved_at is not None
    assert replay.id == approved.id
    assert after_apply_replay.id == approved.id
    assert after_supersession_replay.id == change_request.id


def test_rollback_rejects_the_active_default_as_its_own_target(session: Session) -> None:
    service = governance_service()
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    current = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Initial governed default",
        evaluation_report=passing_report(),
        idempotency_key="active-default",
    )
    service.approve_change_request(
        session, request_id=current.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=current.id, actor=submitter, application_reason="Release"
    )

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_rollback_request(
            session,
            actor=submitter,
            target_request_id=current.id,
            request_reason="No-op rollback",
            idempotency_key="active-default-rollback",
        )

    assert error.value.code == "default_rollback_target_invalid"


def test_rollback_rejects_a_historical_request_with_the_active_configuration(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = governance_service()
    monkeypatch.setattr(service, "supports_generation_provider", lambda *_: True)
    submitter = platform_admin(session)
    approver = platform_admin(session, subject="platform-approver")
    original = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Initial governed default",
        evaluation_report=passing_report(),
        idempotency_key="historical-active-original",
    )
    service.approve_change_request(
        session, request_id=original.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=original.id, actor=submitter, application_reason="Release"
    )
    replacement = service.submit_change_request(
        session,
        actor=submitter,
        provider_name="fake",
        model_version="fake-v2",
        prompt_version="generator-v1",
        request_reason="Replacement governed default",
        evaluation_report=passing_report(model_id="fake-v2", baseline_model_id="fake-v1"),
        idempotency_key="historical-active-replacement",
    )
    service.approve_change_request(
        session, request_id=replacement.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=replacement.id, actor=submitter, application_reason="Release"
    )
    rollback = service.submit_rollback_request(
        session,
        actor=submitter,
        target_request_id=original.id,
        request_reason="Restore original default",
        idempotency_key="historical-active-restore",
    )
    service.approve_change_request(
        session, request_id=rollback.id, actor=approver, approval_reason="Verified"
    )
    service.apply_change_request(
        session, request_id=rollback.id, actor=submitter, application_reason="Restore"
    )

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_rollback_request(
            session,
            actor=submitter,
            target_request_id=original.id,
            request_reason="No-op rollback to the current configuration",
            idempotency_key="historical-active-noop",
        )

    assert error.value.code == "default_rollback_target_invalid"
