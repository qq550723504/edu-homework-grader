from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import Role
from ..services.guardian_consents import (
    GuardianConsentConflictError,
    GuardianConsentError,
    GuardianConsentNotFoundError,
    grant_guardian_consent,
    withdraw_guardian_consent,
)


router = APIRouter(prefix="/v1/admin/students", tags=["guardian consent"])


class GrantGuardianConsentRequest(BaseModel):
    notice_version: str = Field(min_length=1, max_length=50)
    evidence_reference: str = Field(min_length=1, max_length=100)
    version: int = Field(ge=0)


class WithdrawGuardianConsentRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=0)


@router.post("/{student_id}/guardian-consent/grant")
def grant_guardian_consent_route(
    student_id: UUID,
    body: GrantGuardianConsentRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            consent = grant_guardian_consent(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                student_id=student_id,
                notice_version=body.notice_version,
                evidence_reference=body.evidence_reference,
                expected_version=body.version,
            )
    except GuardianConsentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except GuardianConsentConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except GuardianConsentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return {"status": consent.status.value, "version": consent.version}


@router.post("/{student_id}/guardian-consent/withdraw")
def withdraw_guardian_consent_route(
    student_id: UUID,
    body: WithdrawGuardianConsentRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            consent = withdraw_guardian_consent(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                student_id=student_id,
                reason=body.reason,
                expected_version=body.version,
            )
    except GuardianConsentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except GuardianConsentConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except GuardianConsentError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return {"status": consent.status.value, "version": consent.version}
