from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import AuditLog, ClassTeacher, Classroom, Role, User
from ..services.roster import RosterValidationError, import_roster, parse_roster


router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateClassRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


@router.post("/students/import")
async def import_students(
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, int]:
    try:
        rows = parse_roster(await file.read())
        return {"imported": import_roster(session, principal, rows)}
    except RosterValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error


@router.post("/classes", status_code=status.HTTP_201_CREATED)
def create_class(
    body: CreateClassRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    session.rollback()
    with session.begin():
        classroom = Classroom(tenant_id=UUID(principal.tenant_id), code=body.code, name=body.name)
        session.add(classroom)
        session.flush()
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="class.created",
            target_type="class",
            target_id=classroom.id,
            metadata={},
        )
    return {"id": str(classroom.id), "code": classroom.code, "name": classroom.name}


@router.put("/classes/{class_id}/teachers/{teacher_id}")
def assign_teacher(
    class_id: UUID,
    teacher_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    session.rollback()
    with session.begin():
        classroom = session.scalar(
            select(Classroom).where(
                Classroom.id == class_id, Classroom.tenant_id == UUID(principal.tenant_id)
            )
        )
        teacher = session.scalar(
            select(User).where(
                User.id == teacher_id,
                User.tenant_id == UUID(principal.tenant_id),
                User.role == Role.TEACHER,
            )
        )
        if classroom is None or teacher is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        if session.get(ClassTeacher, (classroom.id, teacher.id)) is None:
            session.add(ClassTeacher(class_id=classroom.id, teacher_id=teacher.id))
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="class.teacher_assigned",
            target_type="class",
            target_id=classroom.id,
            metadata={"teacher_id": str(teacher.id)},
        )
    return {"class_id": str(classroom.id), "teacher_id": str(teacher.id)}


@router.get("/audit-logs")
def list_audit_logs(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    event_type: str | None = None,
) -> dict[str, object]:
    statement = select(AuditLog).where(AuditLog.tenant_id == UUID(principal.tenant_id))
    if event_type is not None:
        statement = statement.where(AuditLog.event_type == event_type)
    entries = session.scalars(
        statement.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            {
                "id": str(entry.id),
                "event_type": entry.event_type,
                "target_type": entry.target_type,
                "target_id": str(entry.target_id),
                "metadata": entry.metadata_json,
            }
            for entry in entries
        ],
        "limit": limit,
        "offset": offset,
    }
