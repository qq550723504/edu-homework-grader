from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import CurrentPrincipal, get_current_principal
from .db import get_session
from .models import (
    ACTIVE_PRIVACY_REQUEST_STATUSES,
    GuardianConsentStatus,
    PrivacyRequest,
    Role,
    StudentGuardianConsent,
)


def require_role(role: Role) -> Callable[[CurrentPrincipal], CurrentPrincipal]:
    def dependency(
        principal: Annotated[CurrentPrincipal, Depends(get_current_principal)],
    ) -> CurrentPrincipal:
        if principal.role is not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        return principal

    return dependency


def require_student_consent(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.STUDENT))],
    session: Annotated[Session, Depends(get_session)],
) -> CurrentPrincipal:
    consent = session.get(StudentGuardianConsent, UUID(principal.user_id))
    if consent is not None and consent.status not in {
        GuardianConsentStatus.NOT_REQUIRED,
        GuardianConsentStatus.GRANTED,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="guardian consent required",
        )
    return principal


def require_student_processing_allowed(
    principal: Annotated[CurrentPrincipal, Depends(require_student_consent)],
    session: Annotated[Session, Depends(get_session)],
) -> CurrentPrincipal:
    active_request = session.scalar(
        select(PrivacyRequest.id).where(
            PrivacyRequest.student_id == UUID(principal.user_id),
            PrivacyRequest.status.in_(ACTIVE_PRIVACY_REQUEST_STATUSES),
        )
    )
    if active_request is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="data processing restricted",
        )
    return principal
