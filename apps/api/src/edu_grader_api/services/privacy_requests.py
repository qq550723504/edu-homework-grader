from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import (
    ACTIVE_PRIVACY_REQUEST_STATUSES,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Role,
    User,
    utc_now,
)


class PrivacyRequestError(ValueError):
    pass


class PrivacyRequestNotFoundError(PrivacyRequestError):
    pass


class PrivacyRequestConflictError(PrivacyRequestError):
    pass


def create_privacy_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    student_id: UUID,
    reason: str,
) -> PrivacyRequest:
    student = session.scalar(
        select(User).where(
            User.id == student_id,
            User.tenant_id == tenant_id,
            User.role == Role.STUDENT,
        )
    )
    if student is None:
        raise PrivacyRequestNotFoundError("student not found")
    _validate_reason(reason, "reason")
    if session.scalar(
        select(PrivacyRequest.id).where(
            PrivacyRequest.student_id == student_id,
            PrivacyRequest.status.in_(ACTIVE_PRIVACY_REQUEST_STATUSES),
        )
    ):
        raise PrivacyRequestConflictError("student already has an active privacy request")
    request = PrivacyRequest(
        tenant_id=tenant_id,
        student_id=student_id,
        request_type=PrivacyRequestType.ERASURE,
        status=PrivacyRequestStatus.REQUESTED,
        reason=reason.strip(),
        requested_by_user_id=actor_user_id,
    )
    session.add(request)
    session.flush()
    _append_event(session, request=request, actor_user_id=actor_user_id, event_type="created")
    return request


def hold_privacy_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    reason: str,
    expected_version: int,
) -> PrivacyRequest:
    request = _get_request(session, tenant_id=tenant_id, request_id=request_id)
    _require_transition(
        request,
        expected_version=expected_version,
        allowed_statuses={PrivacyRequestStatus.REQUESTED},
    )
    _validate_reason(reason, "hold reason")
    request.status = PrivacyRequestStatus.LEGAL_HOLD
    request.hold_reason = reason.strip()
    request.decided_by_user_id = actor_user_id
    request.decided_at = utc_now()
    request.version += 1
    _append_event(session, request=request, actor_user_id=actor_user_id, event_type="held")
    return request


def approve_privacy_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    eligible_for_deletion_at: datetime,
    expected_version: int,
) -> PrivacyRequest:
    request = _get_request(session, tenant_id=tenant_id, request_id=request_id)
    _require_transition(
        request,
        expected_version=expected_version,
        allowed_statuses={PrivacyRequestStatus.REQUESTED},
    )
    if eligible_for_deletion_at < request.requested_at:
        raise PrivacyRequestError("eligible deletion time cannot precede the request")
    request.status = PrivacyRequestStatus.APPROVED
    request.decided_by_user_id = actor_user_id
    request.decided_at = utc_now()
    request.eligible_for_deletion_at = eligible_for_deletion_at
    request.version += 1
    _append_event(session, request=request, actor_user_id=actor_user_id, event_type="approved")
    return request


def reject_privacy_request(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    request_id: UUID,
    reason: str,
    expected_version: int,
) -> PrivacyRequest:
    request = _get_request(session, tenant_id=tenant_id, request_id=request_id)
    _require_transition(
        request,
        expected_version=expected_version,
        allowed_statuses={PrivacyRequestStatus.REQUESTED, PrivacyRequestStatus.LEGAL_HOLD},
    )
    _validate_reason(reason, "rejection reason")
    request.status = PrivacyRequestStatus.REJECTED
    request.hold_reason = None
    request.decided_by_user_id = actor_user_id
    request.decided_at = utc_now()
    request.version += 1
    _append_event(session, request=request, actor_user_id=actor_user_id, event_type="rejected")
    return request


def _get_request(session: Session, *, tenant_id: UUID, request_id: UUID) -> PrivacyRequest:
    request = session.scalar(
        select(PrivacyRequest)
        .where(PrivacyRequest.id == request_id, PrivacyRequest.tenant_id == tenant_id)
        .with_for_update()
    )
    if request is None:
        raise PrivacyRequestNotFoundError("privacy request not found")
    return request


def _require_transition(
    request: PrivacyRequest,
    *,
    expected_version: int,
    allowed_statuses: set[PrivacyRequestStatus],
) -> None:
    if request.version != expected_version:
        raise PrivacyRequestConflictError("privacy request changed")
    if request.status not in allowed_statuses:
        raise PrivacyRequestError("privacy request cannot transition from its current status")


def _validate_reason(reason: str, field_name: str) -> None:
    if not reason.strip():
        raise PrivacyRequestError(f"{field_name} is required")


def _append_event(
    session: Session,
    *,
    request: PrivacyRequest,
    actor_user_id: UUID,
    event_type: str,
) -> None:
    metadata: dict[str, object] = {
        "request_type": request.request_type.value,
        "status": request.status.value,
        "version": request.version,
    }
    if request.eligible_for_deletion_at is not None:
        metadata["eligible_for_deletion_at"] = request.eligible_for_deletion_at.isoformat()
    append_audit_event(
        session,
        tenant_id=request.tenant_id,
        actor_user_id=actor_user_id,
        event_type=f"privacy_request.{event_type}",
        target_type="privacy_request",
        target_id=request.id,
        metadata=metadata,
    )
