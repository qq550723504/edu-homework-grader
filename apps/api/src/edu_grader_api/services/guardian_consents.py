import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import GuardianConsentStatus, Role, StudentGuardianConsent, User, utc_now


class GuardianConsentError(ValueError):
    pass


class GuardianConsentNotFoundError(GuardianConsentError):
    pass


class GuardianConsentConflictError(GuardianConsentError):
    pass


SENSITIVE_EVIDENCE_REFERENCE = re.compile(r"@|\d{11,}|[\x00-\x1f\x7f]")


def grant_guardian_consent(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    student_id: UUID,
    notice_version: str,
    evidence_reference: str,
    expected_version: int,
) -> StudentGuardianConsent:
    consent = _get_required_consent(session, tenant_id=tenant_id, student_id=student_id)
    if consent.version != expected_version:
        raise GuardianConsentConflictError("guardian consent changed")
    notice_version = notice_version.strip()
    evidence_reference = evidence_reference.strip()
    if not notice_version or not evidence_reference:
        raise GuardianConsentError("notice version and evidence reference are required")
    if len(notice_version) > 50 or len(evidence_reference) > 100:
        raise GuardianConsentError("guardian consent details exceed allowed length")
    if SENSITIVE_EVIDENCE_REFERENCE.search(evidence_reference):
        raise GuardianConsentError("evidence reference must not contain personal contact data")

    consent.status = GuardianConsentStatus.GRANTED
    consent.notice_version = notice_version
    consent.evidence_reference = evidence_reference
    consent.verified_by_user_id = actor_user_id
    consent.granted_at = utc_now()
    consent.withdrawn_at = None
    consent.withdrawal_reason = None
    consent.version += 1
    append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type="guardian_consent.granted",
        target_type="student",
        target_id=student_id,
        metadata={
            "status": consent.status.value,
            "notice_version": notice_version,
            "evidence_reference": evidence_reference,
            "version": consent.version,
        },
    )
    return consent


def withdraw_guardian_consent(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    student_id: UUID,
    reason: str,
    expected_version: int,
) -> StudentGuardianConsent:
    consent = _get_required_consent(session, tenant_id=tenant_id, student_id=student_id)
    if consent.version != expected_version:
        raise GuardianConsentConflictError("guardian consent changed")
    if consent.status != GuardianConsentStatus.GRANTED:
        raise GuardianConsentError("guardian consent is not granted")
    reason = reason.strip()
    if not reason:
        raise GuardianConsentError("withdrawal reason is required")

    consent.status = GuardianConsentStatus.WITHDRAWN
    consent.verified_by_user_id = actor_user_id
    consent.withdrawn_at = utc_now()
    consent.withdrawal_reason = reason
    consent.version += 1
    append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type="guardian_consent.withdrawn",
        target_type="student",
        target_id=student_id,
        metadata={"status": consent.status.value, "version": consent.version},
    )
    return consent


def _get_required_consent(
    session: Session, *, tenant_id: UUID, student_id: UUID
) -> StudentGuardianConsent:
    student = session.scalar(
        select(User).where(
            User.id == student_id,
            User.tenant_id == tenant_id,
            User.role == Role.STUDENT,
        )
    )
    consent = session.get(StudentGuardianConsent, student_id) if student is not None else None
    if consent is None or not consent.requires_guardian_consent:
        raise GuardianConsentNotFoundError("guardian consent record not found")
    return consent
