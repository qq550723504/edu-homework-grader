from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import Role
from ..services.privacy_requests import (
    PrivacyRequestConflictError,
    PrivacyRequestError,
    PrivacyRequestNotFoundError,
    approve_privacy_request,
    create_privacy_request,
    hold_privacy_request,
    reject_privacy_request,
)


router = APIRouter(prefix="/v1/admin", tags=["privacy requests"])


class CreatePrivacyRequestBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class HoldPrivacyRequestBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=0)


class ApprovePrivacyRequestBody(BaseModel):
    eligible_for_deletion_at: datetime
    version: int = Field(ge=0)


class RejectPrivacyRequestBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    version: int = Field(ge=0)


@router.post("/students/{student_id}/privacy-requests", status_code=status.HTTP_201_CREATED)
def create_privacy_request_route(
    student_id: UUID,
    body: CreatePrivacyRequestBody,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            request = create_privacy_request(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                student_id=student_id,
                reason=body.reason,
            )
    except PrivacyRequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found") from None
    except PrivacyRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PrivacyRequestError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return {"id": str(request.id), "status": request.status.value, "version": request.version}


@router.post("/privacy-requests/{request_id}/hold")
def hold_privacy_request_route(
    request_id: UUID,
    body: HoldPrivacyRequestBody,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return _transition_response(
        session,
        operation=lambda: hold_privacy_request(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            request_id=request_id,
            reason=body.reason,
            expected_version=body.version,
        ),
    )


@router.post("/privacy-requests/{request_id}/approve")
def approve_privacy_request_route(
    request_id: UUID,
    body: ApprovePrivacyRequestBody,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return _transition_response(
        session,
        operation=lambda: approve_privacy_request(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            request_id=request_id,
            eligible_for_deletion_at=body.eligible_for_deletion_at,
            expected_version=body.version,
        ),
    )


@router.post("/privacy-requests/{request_id}/reject")
def reject_privacy_request_route(
    request_id: UUID,
    body: RejectPrivacyRequestBody,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    return _transition_response(
        session,
        operation=lambda: reject_privacy_request(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            request_id=request_id,
            reason=body.reason,
            expected_version=body.version,
        ),
    )


def _transition_response(session: Session, *, operation) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            request = operation()
    except PrivacyRequestNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found") from None
    except PrivacyRequestConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except PrivacyRequestError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return {"status": request.status.value, "version": request.version}
