from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role, require_student_processing_allowed
from ..models import ReviewAppeal, Role
from ..services.appeals import (
    AppealAccessError,
    AppealConflictError,
    create_student_appeal,
    decide_appeal,
)

router = APIRouter(prefix="/v1/student", tags=["student appeals"])
teacher_router = APIRouter(prefix="/v1/review-appeals", tags=["teacher appeals"])


class CreateAppealRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)


class DecideAppealRequest(BaseModel):
    approve: bool
    version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=2_000)


@router.post("/attempts/{attempt_id}/appeals", status_code=status.HTTP_201_CREATED)
def create_appeal_route(
    attempt_id: UUID,
    body: CreateAppealRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_student_processing_allowed)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            appeal = create_student_appeal(
                session,
                tenant_id=UUID(principal.tenant_id),
                student_id=UUID(principal.user_id),
                attempt_id=attempt_id,
                reason=body.reason,
            )
    except AppealAccessError:
        raise HTTPException(status_code=404, detail="resource not found") from None
    except AppealConflictError:
        raise HTTPException(status_code=409, detail="open appeal already exists") from None
    return {"id": str(appeal.id), "status": appeal.status.value}


@router.get("/appeals")
def list_student_appeals(
    principal: Annotated[CurrentPrincipal, Depends(require_student_processing_allowed)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, str]]]:
    appeals = list(
        session.scalars(
            select(ReviewAppeal)
            .where(ReviewAppeal.student_id == UUID(principal.user_id))
            .order_by(ReviewAppeal.created_at, ReviewAppeal.id)
        )
    )
    return {
        "appeals": [
            {
                "id": str(appeal.id),
                "attempt_id": str(appeal.original_attempt_id),
                "status": appeal.status.value,
            }
            for appeal in appeals
        ]
    }


@teacher_router.post("/{appeal_id}/decisions", status_code=status.HTTP_201_CREATED)
def decide_appeal_route(
    appeal_id: UUID,
    body: DecideAppealRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | None]:
    try:
        session.rollback()
        with session.begin():
            link = decide_appeal(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                appeal_id=appeal_id,
                approve=body.approve,
                version=body.version,
                reason=body.reason,
            )
    except AppealAccessError:
        raise HTTPException(status_code=404, detail="resource not found") from None
    except AppealConflictError:
        raise HTTPException(status_code=409, detail="appeal changed") from None
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"correction_attempt_id": str(link.correction_attempt_id) if link else None}
