from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal, get_current_principal
from ..db import get_session
from ..models import ClassTeacher, Classroom, Enrollment, Role


router = APIRouter(prefix="/v1/classes", tags=["classes"])


@router.get("/{class_id}")
def get_class(
    class_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(get_current_principal)],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    classroom = session.scalar(
        select(Classroom).where(
            Classroom.id == class_id, Classroom.tenant_id == UUID(principal.tenant_id)
        )
    )
    if classroom is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    if (
        principal.role is Role.TEACHER
        and session.get(ClassTeacher, (class_id, UUID(principal.user_id))) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    if (
        principal.role is Role.STUDENT
        and session.get(Enrollment, (class_id, UUID(principal.user_id))) is None
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return {"id": str(classroom.id), "code": classroom.code, "name": classroom.name}
