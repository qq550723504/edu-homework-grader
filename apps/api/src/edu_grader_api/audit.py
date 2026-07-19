from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditChainHead, AuditLog, utc_now
from .settings import settings


class AuditValidationError(ValueError):
    """Raised when an audit event would contain sensitive or ambiguous data."""


_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "answer",
        "answer_json",
        "authorization",
        "token",
        "password",
        "oidc_subject",
        "school_id",
        "display_name",
        "email",
    }
)


@dataclass(frozen=True)
class AuditChainVerification:
    valid: bool
    first_invalid_sequence: int | None = None


def append_audit_event(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    target_type: str,
    target_id: UUID,
    metadata: Mapping[str, object],
) -> AuditLog:
    safe_metadata = _safe_metadata(metadata)
    head = session.scalar(
        select(AuditChainHead).where(AuditChainHead.tenant_id == tenant_id).with_for_update()
    )
    if head is None:
        head = AuditChainHead(tenant_id=tenant_id)
        session.add(head)
        session.flush()
    occurred_at = utc_now()
    sequence = head.next_sequence
    previous_hash = head.latest_entry_hash
    entry_hash = _entry_hash(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        occurred_at=occurred_at,
        metadata=safe_metadata,
        sequence=sequence,
        previous_hash=previous_hash,
        key_version=settings.audit_hmac_key_version,
    )
    entry = AuditLog(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        occurred_at=occurred_at,
        metadata_json=safe_metadata,
        sequence=sequence,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        signature=_sign(entry_hash),
        key_version=settings.audit_hmac_key_version,
    )
    head.next_sequence = sequence + 1
    head.latest_entry_hash = entry_hash
    session.add(entry)
    session.flush()
    return entry


def verify_audit_chain(session: Session, *, tenant_id: UUID) -> AuditChainVerification:
    previous_hash = ""
    entries = session.scalars(
        select(AuditLog)
        .where(AuditLog.tenant_id == tenant_id)
        .order_by(AuditLog.sequence, AuditLog.id)
    )
    for entry in entries:
        if entry.key_version == "legacy-unsigned":
            previous_hash = entry.entry_hash
            continue
        expected_hash = _entry_hash(
            tenant_id=entry.tenant_id,
            actor_user_id=entry.actor_user_id,
            event_type=entry.event_type,
            target_type=entry.target_type,
            target_id=entry.target_id,
            occurred_at=entry.occurred_at,
            metadata=entry.metadata_json,
            sequence=entry.sequence,
            previous_hash=previous_hash,
            key_version=entry.key_version,
        )
        if (
            entry.previous_hash != previous_hash
            or entry.entry_hash != expected_hash
            or not hmac.compare_digest(entry.signature, _sign(expected_hash))
        ):
            return AuditChainVerification(valid=False, first_invalid_sequence=entry.sequence)
        previous_hash = entry.entry_hash
    return AuditChainVerification(valid=True)


def _safe_metadata(metadata: Mapping[str, object]) -> dict[str, object]:
    return _safe_value(metadata)


def _safe_value(value: object) -> object:
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise AuditValidationError("audit metadata keys must be strings")
            if key.casefold() in _FORBIDDEN_METADATA_KEYS:
                raise AuditValidationError(f"forbidden audit metadata field: {key}")
            result[key] = _safe_value(item)
        return result
    if isinstance(value, list):
        return [_safe_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise AuditValidationError("audit metadata values must be JSON primitives")


def _entry_hash(
    *,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    target_type: str,
    target_id: UUID,
    occurred_at: datetime,
    metadata: Mapping[str, object],
    sequence: int,
    previous_hash: str,
    key_version: str,
) -> str:
    occurred_at_utc = (
        occurred_at.replace(tzinfo=timezone.utc)
        if occurred_at.tzinfo is None
        else occurred_at.astimezone(timezone.utc)
    )
    payload = {
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "event_type": event_type,
        "key_version": key_version,
        "metadata": _safe_metadata(metadata),
        "occurred_at": occurred_at_utc.isoformat(),
        "previous_hash": previous_hash,
        "sequence": sequence,
        "target_id": str(target_id),
        "target_type": target_type,
        "tenant_id": str(tenant_id),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _sign(entry_hash: str) -> str:
    return hmac.new(
        settings.audit_hmac_key.encode("utf-8"), entry_hash.encode("ascii"), hashlib.sha256
    ).hexdigest()
