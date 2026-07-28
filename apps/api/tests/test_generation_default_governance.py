from datetime import datetime, timezone
from importlib import import_module
from importlib.util import find_spec

import pytest
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
from edu_grader_api.services.ai_evaluation_operational import OperationalEvaluationReport


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


def passing_report(*, model_id: str = "fake-v1", provider_name: str = "fake") -> dict[str, object]:
    passing_gate = {
        "policy_id": "generation-default-governance-v1",
        "promotion_eligible": True,
        "metrics": {},
        "violations": [],
        "rejection_reason_counts": {},
        "cost_per_final_accepted_question": None,
        "end_to_end_duration_ms": {},
    }
    return OperationalEvaluationReport(
        spec_id="generation-default-governance-v1",
        exporter_version="operational-export-v1",
        run_id="run-001",
        tenant_id="pilot",
        watermark=datetime(2026, 7, 28, tzinfo=timezone.utc),
        baseline={
            "provider_name": "fake",
            "model_id": "fake-v0",
            "prompt_version": "generator-v1",
            "validator_version": "verification-v1",
        },
        candidate={
            "provider_name": provider_name,
            "model_id": model_id,
            "prompt_version": "generator-v1",
            "validator_version": "verification-v1",
        },
        promotion_eligible=True,
        export_manifest={
            "exporter_version": "operational-export-v1",
            "run_id": "run-001",
            "tenant_id": "pilot",
            "watermark": datetime(2026, 7, 28, tzinfo=timezone.utc),
            "record_count": 12,
            "issue_count": 0,
            "record_digest": "a" * 64,
            "source_counts": {"accepted_directly": 12},
        },
        baseline_gate=passing_gate,
        candidate_gate=passing_gate,
    ).model_dump(mode="json")


def governance_service():
    assert find_spec("edu_grader_api.services.generation_default_governance") is not None
    return import_module("edu_grader_api.services.generation_default_governance")


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
    report = passing_report()
    report["candidate_gate"] = None

    with pytest.raises(service.GenerationDefaultGovernanceError) as error:
        service.submit_change_request(
            session,
            actor=admin,
            provider_name="fake",
            model_version="fake-v1",
            prompt_version="generator-v1",
            request_reason="Promote unverified candidate",
            evaluation_report=report,
            idempotency_key="missing-gate-evidence",
        )

    assert error.value.code == "evaluation_not_promotion_eligible"


def test_submit_rejects_gate_that_claims_eligibility_despite_violations(session: Session) -> None:
    service = governance_service()
    admin = platform_admin(session)
    report = passing_report()
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
            evaluation_report=report,
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
        evaluation_report=passing_report(),
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


def test_rollback_is_a_new_approved_change_request(session: Session) -> None:
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
        model_version="fake-v1",
        prompt_version="generator-v1",
        request_reason="Upgrade governed default",
        evaluation_report=passing_report(),
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
    service.approve_change_request(
        session, request_id=rollback.id, actor=approver, approval_reason="Rollback verified"
    )
    service.apply_change_request(
        session, request_id=rollback.id, actor=submitter, application_reason="Rollback"
    )

    assert service.resolve_active_default(session).model_version == "fake-v1"
    assert replacement.status is GenerationDefaultChangeStatus.ROLLED_BACK
    assert rollback.status is GenerationDefaultChangeStatus.APPLIED


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
