"""Governed, auditable selection of the default AI generation configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from edu_generator.model_snapshots import validate_immutable_openai_model_id
from edu_generator.prompt_templates import resolve_prompt_template
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import (
    GenerationControlState,
    GenerationDefaultChangeRequest,
    GenerationDefaultChangeStatus,
    GenerationDefaultConfiguration,
    GenerationDefaultSelection,
    User,
    utc_now,
)
from .generation_governance import controls_for_target
from .generation_provider_registry import supports_generation_provider


class GenerationDefaultGovernanceError(ValueError):
    """Stable failure code for default-generation governance operations."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ResolvedGenerationDefault:
    provider_name: str
    model_version: str
    prompt_version: str
    prompt_template_fingerprint: str


_SUPPORTED_QUESTION_TYPES = ("M1", "M2", "E1", "E2", "E3", "E4")


def submit_change_request(
    session: Session,
    *,
    actor: User,
    provider_name: str,
    model_version: str,
    prompt_version: str,
    request_reason: str,
    evaluation_report: dict[str, object],
    idempotency_key: str,
) -> GenerationDefaultChangeRequest:
    report = _validated_report(evaluation_report)
    _assert_candidate_matches(
        report,
        provider_name=provider_name,
        model_version=model_version,
        prompt_version=prompt_version,
    )
    if not supports_generation_provider(provider_name, model_version):
        raise GenerationDefaultGovernanceError("default_provider_not_configured")
    if provider_name == "openai":
        try:
            validate_immutable_openai_model_id(model_version)
        except ValueError as exc:
            raise GenerationDefaultGovernanceError("default_model_not_immutable") from exc
    try:
        template = resolve_prompt_template(prompt_version, _SUPPORTED_QUESTION_TYPES)
    except ValueError as exc:
        raise GenerationDefaultGovernanceError("default_prompt_template_unavailable") from exc
    if report.candidate.prompt_template_fingerprint != template.fingerprint:
        raise GenerationDefaultGovernanceError("evaluation_prompt_template_mismatch")
    if not request_reason.strip():
        raise GenerationDefaultGovernanceError("default_change_request_reason_required")
    _assert_global_default_components_active(
        session,
        tenant_id=actor.tenant_id,
        provider_name=provider_name,
        model_version=model_version,
        prompt_version=prompt_version,
    )

    report_payload = report.model_dump(mode="json")
    report_sha256 = _canonical_sha256(report_payload)
    request_digest = _canonical_sha256(
        {
            "provider_name": provider_name,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "request_reason": request_reason,
            "evaluation_report_sha256": report_sha256,
        }
    )
    existing = session.scalar(
        select(GenerationDefaultChangeRequest).where(
            GenerationDefaultChangeRequest.submitted_by_user_id == actor.id,
            GenerationDefaultChangeRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
        return existing

    selection = session.get(GenerationDefaultSelection, "global")
    if selection is not None:
        _assert_report_baseline_matches_selection(report, selection)

    configuration = session.scalar(
        select(GenerationDefaultConfiguration).where(
            GenerationDefaultConfiguration.provider_name == provider_name,
            GenerationDefaultConfiguration.model_version == model_version,
            GenerationDefaultConfiguration.prompt_version == prompt_version,
            GenerationDefaultConfiguration.prompt_template_fingerprint == template.fingerprint,
        )
    )
    if configuration is None:
        configuration = _create_or_load_configuration(
            session,
            actor=actor,
            provider_name=provider_name,
            model_version=model_version,
            prompt_version=prompt_version,
            prompt_template_fingerprint=template.fingerprint,
        )

    change_request = GenerationDefaultChangeRequest(
        configuration=configuration,
        status=GenerationDefaultChangeStatus.PENDING_APPROVAL,
        request_reason=request_reason,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        evaluation_report_sha256=report_sha256,
        evaluation_record_digest=report.export_manifest.record_digest,
        evaluation_run_id=report.run_id,
        evaluation_spec_id=report.spec_id,
        evaluation_watermark=report.watermark,
        evaluated_against_selection_request_id=(
            selection.applied_change_request_id if selection is not None else None
        ),
        evaluation_summary_json={
            "candidate": report.candidate.model_dump(mode="json"),
            "promotion_eligible": report.promotion_eligible,
            "record_count": report.export_manifest.record_count,
            "issue_count": report.export_manifest.issue_count,
            "baseline_gate": report.baseline_gate.model_dump(mode="json"),
            "candidate_gate": report.candidate_gate.model_dump(mode="json"),
            "metric_comparisons": {
                key: comparison.model_dump(mode="json")
                for key, comparison in report.metric_comparisons.items()
            },
            "violations": [violation.model_dump(mode="json") for violation in report.violations],
            "record_digest": report.export_manifest.record_digest,
            "run_id": report.run_id,
            "spec_id": report.spec_id,
            "watermark": report.watermark.isoformat(),
        },
        submitted_by_user_id=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(change_request)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(GenerationDefaultChangeRequest).where(
                GenerationDefaultChangeRequest.submitted_by_user_id == actor.id,
                GenerationDefaultChangeRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise GenerationDefaultGovernanceError("default_change_request_conflict") from None
        if existing.request_digest != request_digest:
            raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
        return existing
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_generation_default.change_submitted",
        target_type="generation_default_change_request",
        target_id=change_request.id,
        metadata={
            "configuration_id": configuration.id,
            "provider_name": provider_name,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "evaluation_report_sha256": report_sha256,
        },
    )
    return change_request


def approve_change_request(
    session: Session,
    *,
    request_id: UUID,
    actor: User,
    approval_reason: str,
    idempotency_key: str | None = None,
) -> GenerationDefaultChangeRequest:
    change_request = _locked_change_request(session, request_id)
    if change_request is None:
        raise GenerationDefaultGovernanceError("default_change_not_found")
    if change_request.submitted_by_user_id == actor.id:
        raise GenerationDefaultGovernanceError("default_change_self_approval_forbidden")
    digest = _decision_digest("approve", approval_reason)
    if _decision_replay(change_request, idempotency_key=idempotency_key, digest=digest):
        return change_request
    if change_request.status is not GenerationDefaultChangeStatus.PENDING_APPROVAL:
        raise GenerationDefaultGovernanceError("default_change_not_pending_approval")
    if not approval_reason.strip():
        raise GenerationDefaultGovernanceError("default_change_approval_reason_required")

    change_request.status = GenerationDefaultChangeStatus.APPROVED
    change_request.approval_reason = approval_reason
    change_request.approved_by_user_id = actor.id
    change_request.approved_at = utc_now()
    change_request.decision_idempotency_key = idempotency_key
    change_request.decision_request_digest = digest if idempotency_key is not None else None
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_generation_default.change_approved",
        target_type="generation_default_change_request",
        target_id=change_request.id,
        metadata={"configuration_id": change_request.configuration_id},
    )
    session.flush()
    return change_request


def reject_change_request(
    session: Session,
    *,
    request_id: UUID,
    actor: User,
    rejection_reason: str,
    idempotency_key: str | None = None,
) -> GenerationDefaultChangeRequest:
    change_request = _locked_change_request(session, request_id)
    if change_request is None:
        raise GenerationDefaultGovernanceError("default_change_not_found")
    if change_request.submitted_by_user_id == actor.id:
        raise GenerationDefaultGovernanceError("default_change_self_approval_forbidden")
    digest = _decision_digest("reject", rejection_reason)
    if _decision_replay(change_request, idempotency_key=idempotency_key, digest=digest):
        return change_request
    if change_request.status is not GenerationDefaultChangeStatus.PENDING_APPROVAL:
        raise GenerationDefaultGovernanceError("default_change_not_pending_approval")
    if not rejection_reason.strip():
        raise GenerationDefaultGovernanceError("default_change_rejection_reason_required")
    change_request.status = GenerationDefaultChangeStatus.REJECTED
    change_request.approval_reason = rejection_reason
    change_request.approved_by_user_id = actor.id
    change_request.approved_at = utc_now()
    change_request.decision_idempotency_key = idempotency_key
    change_request.decision_request_digest = digest if idempotency_key is not None else None
    session.flush()
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_generation_default.change_rejected",
        target_type="generation_default_change_request",
        target_id=change_request.id,
        metadata={"configuration_id": change_request.configuration_id},
    )
    return change_request


def apply_change_request(
    session: Session,
    *,
    request_id: UUID,
    actor: User,
    application_reason: str,
    idempotency_key: str | None = None,
) -> GenerationDefaultChangeRequest:
    if not application_reason.strip():
        raise GenerationDefaultGovernanceError("default_change_application_reason_required")
    change_request = session.scalar(
        select(GenerationDefaultChangeRequest)
        .where(GenerationDefaultChangeRequest.id == request_id)
        .with_for_update()
    )
    if change_request is None:
        raise GenerationDefaultGovernanceError("default_change_not_found")
    digest = _decision_digest("apply", application_reason)
    if _application_replay(change_request, idempotency_key=idempotency_key, digest=digest):
        return change_request
    if change_request.status is not GenerationDefaultChangeStatus.APPROVED:
        raise GenerationDefaultGovernanceError("default_change_not_approved")
    configuration = change_request.configuration
    if not supports_generation_provider(configuration.provider_name, configuration.model_version):
        raise GenerationDefaultGovernanceError("default_provider_not_configured")
    _assert_global_default_components_active(
        session,
        tenant_id=actor.tenant_id,
        provider_name=configuration.provider_name,
        model_version=configuration.model_version,
        prompt_version=configuration.prompt_version,
    )
    try:
        template = resolve_prompt_template(configuration.prompt_version, _SUPPORTED_QUESTION_TYPES)
    except ValueError as exc:
        raise GenerationDefaultGovernanceError("default_prompt_template_unavailable") from exc
    if template.fingerprint != configuration.prompt_template_fingerprint:
        raise GenerationDefaultGovernanceError("default_prompt_template_changed") from None

    selection = _locked_global_selection(session)
    active_request_id = selection.applied_change_request_id if selection is not None else None
    if change_request.evaluated_against_selection_request_id != active_request_id:
        raise GenerationDefaultGovernanceError("default_change_stale_selection")
    if selection is not None:
        previous = session.get(GenerationDefaultChangeRequest, selection.applied_change_request_id)
        if previous is not None:
            previous.status = (
                GenerationDefaultChangeStatus.ROLLED_BACK
                if change_request.rollback_source_change_request_id is not None
                else GenerationDefaultChangeStatus.SUPERSEDED
            )
        selection.configuration_id = change_request.configuration_id
        selection.applied_change_request_id = change_request.id
    else:
        session.add(
            GenerationDefaultSelection(
                scope="global",
                configuration_id=change_request.configuration_id,
                applied_change_request_id=change_request.id,
            )
        )
    change_request.status = GenerationDefaultChangeStatus.APPLIED
    change_request.application_reason = application_reason
    change_request.applied_by_user_id = actor.id
    change_request.applied_at = utc_now()
    change_request.application_idempotency_key = idempotency_key
    change_request.application_request_digest = digest if idempotency_key is not None else None
    session.flush()
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_generation_default.change_applied",
        target_type="generation_default_change_request",
        target_id=change_request.id,
        metadata={"configuration_id": change_request.configuration_id},
    )
    return change_request


def submit_rollback_request(
    session: Session,
    *,
    actor: User,
    target_request_id: UUID,
    request_reason: str,
    idempotency_key: str,
) -> GenerationDefaultChangeRequest:
    target = session.get(GenerationDefaultChangeRequest, target_request_id)
    if not request_reason.strip():
        raise GenerationDefaultGovernanceError("default_rollback_reason_required")
    selection = session.get(GenerationDefaultSelection, "global")
    if (
        target is None
        or target.status
        not in {
            GenerationDefaultChangeStatus.SUPERSEDED,
            GenerationDefaultChangeStatus.ROLLED_BACK,
        }
        or selection is None
        or target.id == selection.applied_change_request_id
    ):
        raise GenerationDefaultGovernanceError("default_rollback_target_invalid")
    request_digest = _canonical_sha256(
        {
            "target_request_id": str(target.id),
            "request_reason": request_reason,
            "idempotency_key": idempotency_key,
        }
    )
    existing = session.scalar(
        select(GenerationDefaultChangeRequest).where(
            GenerationDefaultChangeRequest.submitted_by_user_id == actor.id,
            GenerationDefaultChangeRequest.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
        return existing
    rollback = GenerationDefaultChangeRequest(
        configuration_id=target.configuration_id,
        rollback_source_change_request_id=target.id,
        status=GenerationDefaultChangeStatus.PENDING_APPROVAL,
        request_reason=request_reason,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        evaluation_report_sha256=target.evaluation_report_sha256,
        evaluation_record_digest=target.evaluation_record_digest,
        evaluation_run_id=target.evaluation_run_id,
        evaluation_spec_id=target.evaluation_spec_id,
        evaluation_watermark=target.evaluation_watermark,
        evaluated_against_selection_request_id=selection.applied_change_request_id,
        evaluation_summary_json=target.evaluation_summary_json,
        submitted_by_user_id=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(rollback)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(GenerationDefaultChangeRequest).where(
                GenerationDefaultChangeRequest.submitted_by_user_id == actor.id,
                GenerationDefaultChangeRequest.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise GenerationDefaultGovernanceError("default_change_request_conflict") from None
        if existing.request_digest != request_digest:
            raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
        return existing
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_generation_default.rollback_submitted",
        target_type="generation_default_change_request",
        target_id=rollback.id,
        metadata={"rollback_source_change_request_id": target.id},
    )
    return rollback


def resolve_active_default(session: Session) -> ResolvedGenerationDefault:
    selection = session.get(GenerationDefaultSelection, "global")
    if selection is None:
        raise GenerationDefaultGovernanceError("generation_default_not_configured")
    configuration = selection.configuration
    return ResolvedGenerationDefault(
        provider_name=configuration.provider_name,
        model_version=configuration.model_version,
        prompt_version=configuration.prompt_version,
        prompt_template_fingerprint=configuration.prompt_template_fingerprint,
    )


def validate_active_default(session: Session) -> ResolvedGenerationDefault:
    """Ensure the selected default is still executable before declaring readiness."""

    default = resolve_active_default(session)
    if not supports_generation_provider(default.provider_name, default.model_version):
        raise GenerationDefaultGovernanceError("default_provider_not_configured")
    try:
        template = resolve_prompt_template(default.prompt_version, _SUPPORTED_QUESTION_TYPES)
    except ValueError as exc:
        raise GenerationDefaultGovernanceError("default_prompt_template_unavailable") from exc
    if template.fingerprint != default.prompt_template_fingerprint:
        raise GenerationDefaultGovernanceError("default_prompt_template_changed")
    _assert_global_components_active(
        session,
        provider_name=default.provider_name,
        model_version=default.model_version,
        prompt_version=default.prompt_version,
    )
    return default


def _validated_report(payload: dict[str, object]):
    from .ai_evaluation_operational import OperationalEvaluationReport

    try:
        report = OperationalEvaluationReport.model_validate(payload)
    except ValidationError as exc:
        raise GenerationDefaultGovernanceError("evaluation_report_invalid") from exc
    gates = (report.baseline_gate, report.candidate_gate)
    gates_are_eligible = all(
        gate is not None and gate.promotion_eligible and not gate.violations for gate in gates
    )
    evidence_is_eligible = (
        report.promotion_eligible
        and report.export_manifest.issue_count == 0
        and not report.violations
        and gates_are_eligible
        and all(comparison.state != "fail" for comparison in report.metric_comparisons.values())
    )
    if not evidence_is_eligible:
        raise GenerationDefaultGovernanceError("evaluation_not_promotion_eligible")
    return report


def _assert_global_default_components_active(
    session: Session,
    *,
    tenant_id: UUID,
    provider_name: str,
    model_version: str,
    prompt_version: str,
) -> None:
    for target_type, target_key in (
        ("provider", provider_name),
        ("model", model_version),
        ("prompt_version", prompt_version),
    ):
        _, global_state = controls_for_target(
            session,
            tenant_id=tenant_id,
            target_type=target_type,
            target_key=target_key,
        )
        if global_state not in {None, GenerationControlState.ACTIVE}:
            raise GenerationDefaultGovernanceError("default_component_not_active")


def _assert_global_components_active(
    session: Session, *, provider_name: str, model_version: str, prompt_version: str
) -> None:
    from ..models import GenerationGovernanceEntry, GenerationGovernanceTargetType

    for target_type, target_key in (
        (GenerationGovernanceTargetType.PROVIDER, provider_name),
        (GenerationGovernanceTargetType.MODEL, model_version),
        (GenerationGovernanceTargetType.PROMPT_VERSION, prompt_version),
    ):
        entry = session.scalar(
            select(GenerationGovernanceEntry).where(
                GenerationGovernanceEntry.is_global.is_(True),
                GenerationGovernanceEntry.target_type == target_type,
                GenerationGovernanceEntry.target_key == target_key,
            )
        )
        if entry is not None and entry.control_state is not GenerationControlState.ACTIVE:
            raise GenerationDefaultGovernanceError("default_component_not_active")


def _assert_candidate_matches(
    report: object,
    *,
    provider_name: str,
    model_version: str,
    prompt_version: str,
) -> None:
    candidate = report.candidate
    if (
        candidate.provider_name != provider_name
        or candidate.model_id != model_version
        or candidate.prompt_version != prompt_version
    ):
        raise GenerationDefaultGovernanceError("evaluation_candidate_mismatch")


def _assert_report_baseline_matches_selection(
    report: object, selection: GenerationDefaultSelection
) -> None:
    baseline = report.baseline
    configuration = selection.configuration
    if (
        baseline.provider_name != configuration.provider_name
        or baseline.model_id != configuration.model_version
        or baseline.prompt_version != configuration.prompt_version
        or baseline.prompt_template_fingerprint != configuration.prompt_template_fingerprint
    ):
        raise GenerationDefaultGovernanceError("evaluation_baseline_mismatch")


def _locked_change_request(
    session: Session, request_id: UUID
) -> GenerationDefaultChangeRequest | None:
    return session.scalar(
        select(GenerationDefaultChangeRequest)
        .where(GenerationDefaultChangeRequest.id == request_id)
        .with_for_update()
    )


def _locked_global_selection(session: Session) -> GenerationDefaultSelection | None:
    # Row locks do not protect the initial insert because no selection row exists yet.
    # A transaction-scoped advisory lock serializes that first apply on PostgreSQL;
    # SQLite's single-writer behavior already provides the equivalent in local tests.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(896101)"))
    return session.scalar(
        select(GenerationDefaultSelection)
        .where(GenerationDefaultSelection.scope == "global")
        .with_for_update()
    )


def _decision_digest(action: str, reason: str) -> str:
    return _canonical_sha256({"action": action, "reason": reason.strip()})


def _decision_replay(
    request: GenerationDefaultChangeRequest, *, idempotency_key: str | None, digest: str
) -> bool:
    if idempotency_key is None or request.decision_idempotency_key != idempotency_key:
        return False
    if request.decision_request_digest != digest:
        raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
    return request.status is not GenerationDefaultChangeStatus.PENDING_APPROVAL


def _application_replay(
    request: GenerationDefaultChangeRequest, *, idempotency_key: str | None, digest: str
) -> bool:
    if idempotency_key is None or request.application_idempotency_key != idempotency_key:
        return False
    if request.application_request_digest != digest:
        raise GenerationDefaultGovernanceError("default_change_idempotency_conflict")
    return request.status in {
        GenerationDefaultChangeStatus.APPLIED,
        GenerationDefaultChangeStatus.SUPERSEDED,
        GenerationDefaultChangeStatus.ROLLED_BACK,
    }


def _create_or_load_configuration(
    session: Session,
    *,
    actor: User,
    provider_name: str,
    model_version: str,
    prompt_version: str,
    prompt_template_fingerprint: str,
) -> GenerationDefaultConfiguration:
    configuration = GenerationDefaultConfiguration(
        provider_name=provider_name,
        model_version=model_version,
        prompt_version=prompt_version,
        prompt_template_fingerprint=prompt_template_fingerprint,
        created_by_user_id=actor.id,
    )
    try:
        with session.begin_nested():
            session.add(configuration)
            session.flush()
        return configuration
    except IntegrityError:
        pass
    existing = session.scalar(
        select(GenerationDefaultConfiguration).where(
            GenerationDefaultConfiguration.provider_name == provider_name,
            GenerationDefaultConfiguration.model_version == model_version,
            GenerationDefaultConfiguration.prompt_version == prompt_version,
            GenerationDefaultConfiguration.prompt_template_fingerprint
            == prompt_template_fingerprint,
        )
    )
    if existing is None:
        raise GenerationDefaultGovernanceError("default_configuration_conflict")
    return existing


def _canonical_sha256(payload: object) -> str:
    rendered = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()
