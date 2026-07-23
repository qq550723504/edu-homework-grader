from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    GenerationControlState,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType as TargetType,
)


class GenerationGovernanceError(ValueError):
    """Stable governance error with explicit machine-readable failure reason."""

    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


_ALLOWED_TRANSITIONS: dict[GenerationControlState, set[GenerationControlState]] = {
    GenerationControlState.ACTIVE: {
        GenerationControlState.ACTIVE,
        GenerationControlState.CANARY,
        GenerationControlState.PAUSED,
        GenerationControlState.RETIRED,
    },
    GenerationControlState.CANARY: {
        GenerationControlState.ACTIVE,
        GenerationControlState.CANARY,
        GenerationControlState.PAUSED,
        GenerationControlState.RETIRED,
    },
    GenerationControlState.PAUSED: {GenerationControlState.ACTIVE, GenerationControlState.RETIRED},
    GenerationControlState.RETIRED: {GenerationControlState.RETIRED},
}


def allowed_transition(
    from_state: GenerationControlState, to_state: GenerationControlState
) -> bool:
    return to_state in _ALLOWED_TRANSITIONS[from_state]


def assert_generation_configured_components_allowed(
    session: Session,
    *,
    tenant_id: UUID,
    curriculum_profile_id: str,
    prompt_version: str,
    provider_name: str | None = None,
    model_version: str | None = None,
) -> None:
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.GENERATOR,
        target_key="generator",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.CURRICULUM_PROFILE,
        target_key=curriculum_profile_id,
        blocked_code="curriculum_profile_control_blocked",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.PROMPT_VERSION,
        target_key=prompt_version,
        blocked_code="prompt_version_control_blocked",
    )
    if provider_name is not None:
        _assert_component_allowed(
            session,
            tenant_id=tenant_id,
            target_type=TargetType.PROVIDER,
            target_key=provider_name,
            blocked_code="provider_control_blocked",
        )
    if model_version is not None:
        _assert_component_allowed(
            session,
            tenant_id=tenant_id,
            target_type=TargetType.MODEL,
            target_key=model_version,
            blocked_code="model_control_blocked",
        )


def assert_generation_pipeline_allowed(
    session: Session,
    *,
    tenant_id: UUID,
    curriculum_profile_id: str | None,
    prompt_version: str,
    provider_name: str,
    model_version: str,
) -> None:
    if curriculum_profile_id is None:
        raise GenerationGovernanceError("curriculum_profile_not_resolved")
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.GENERATOR,
        target_key="generator",
        blocked_code="generator_control_blocked",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.CURRICULUM_PROFILE,
        target_key=curriculum_profile_id,
        blocked_code="curriculum_profile_control_blocked",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.PROMPT_VERSION,
        target_key=prompt_version,
        blocked_code="prompt_version_control_blocked",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.PROVIDER,
        target_key=provider_name,
        blocked_code="provider_control_blocked",
    )
    _assert_component_allowed(
        session,
        tenant_id=tenant_id,
        target_type=TargetType.MODEL,
        target_key=model_version,
        blocked_code="model_control_blocked",
    )


def allowed_controls_for_target(
    session: Session, *, tenant_id: UUID, target_type: TargetType, target_key: str
) -> tuple[GenerationControlState | None, GenerationControlState | None]:
    tenant_entry = _find_scope_entry(
        session,
        tenant_id=tenant_id,
        target_type=target_type,
        target_key=target_key,
        is_global=False,
    )
    if tenant_entry is not None:
        return tenant_entry.control_state, None

    global_entry = _find_scope_entry(
        session,
        tenant_id=None,
        target_type=target_type,
        target_key=target_key,
        is_global=True,
    )
    if global_entry is None:
        return None, None
    return None, global_entry.control_state


def _assert_component_allowed(
    session: Session,
    *,
    tenant_id: UUID,
    target_type: TargetType,
    target_key: str,
    blocked_code: str | None = None,
) -> None:
    tenant_entry, global_entry = allowed_controls_for_target(
        session, tenant_id=tenant_id, target_type=target_type, target_key=target_key
    )

    if tenant_entry is not None:
        if _is_blocked(tenant_entry):
            raise GenerationGovernanceError(blocked_code or "generation_control_blocked")
        return

    if global_entry is not None and _is_blocked(global_entry, allow_canary=False):
        raise GenerationGovernanceError(blocked_code or "generation_control_blocked")


def _is_blocked(state: GenerationControlState, *, allow_canary: bool = True) -> bool:
    if state in {GenerationControlState.PAUSED, GenerationControlState.RETIRED}:
        return True
    if not allow_canary and state is GenerationControlState.CANARY:
        return True
    return False


def _find_scope_entry(
    session: Session,
    *,
    tenant_id: UUID | None,
    target_type: TargetType,
    target_key: str,
    is_global: bool,
) -> GenerationGovernanceEntry | None:
    statement = select(GenerationGovernanceEntry).where(
        GenerationGovernanceEntry.target_type == target_type,
        GenerationGovernanceEntry.target_key == target_key,
        GenerationGovernanceEntry.is_global == is_global,
    )
    if is_global:
        statement = statement.where(GenerationGovernanceEntry.tenant_id.is_(None))
    else:
        statement = statement.where(
            GenerationGovernanceEntry.tenant_id == tenant_id,
            GenerationGovernanceEntry.is_global == False,  # noqa: E712
        )
    return session.scalar(statement.order_by(GenerationGovernanceEntry.updated_at.desc()).limit(1))


def assert_transition_allowed(
    current: GenerationControlState, target: GenerationControlState
) -> None:
    if not allowed_transition(current, target):
        raise ValueError("invalid_governance_transition")


def assert_transition_is_valid(
    current: GenerationControlState, target: GenerationControlState
) -> None:
    assert_transition_allowed(current, target)
