from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import Role
from ..services.appeals import AppealAccessError, AppealConflictError, create_student_appeal

router = APIRouter(prefix="/v1/student", tags=["student appeals"])


class CreateAppealRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2_000)


@router.post("/attempts/{attempt_id}/appeals", status_code=status.HTTP_201_CREATED)
def create_appeal_route(
    attempt_id: UUID,
    body: CreateAppealRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.STUDENT))],
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
