from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import (
    AuditLog,
    ClassTeacher,
    Classroom,
    GenerationControlState,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    Role,
    User,
)
from ..services.generation_governance import (
    assert_transition_is_valid,
)
from ..services.roster import RosterValidationError, import_roster, parse_roster


router = APIRouter(prefix="/v1/admin", tags=["admin"])


class CreateClassRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class CreateGenerationGovernanceEntryRequest(BaseModel):
    is_global: bool = False
    tenant_id: UUID | None = None
    target_type: GenerationGovernanceTargetType
    target_key: str = Field(min_length=1, max_length=255)
    control_state: GenerationControlState
    note: str | None = Field(default=None, max_length=1_000)


class TransitionGenerationGovernanceEntryRequest(BaseModel):
    control_state: GenerationControlState


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


@router.get("/ai-generation-governance")
def list_ai_generation_governance(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor_tenant_id = UUID(principal.tenant_id)
    statement = select(GenerationGovernanceEntry).where(
        or_(
            GenerationGovernanceEntry.is_global.is_(True),
            and_(
                GenerationGovernanceEntry.is_global.is_(False),
                GenerationGovernanceEntry.tenant_id == actor_tenant_id,
            ),
        )
    )
    entries = session.scalars(statement.order_by(GenerationGovernanceEntry.target_type)).all()
    return {"items": [_governance_entry_payload(entry) for entry in entries]}


@router.post("/ai-generation-governance", status_code=status.HTTP_201_CREATED)
def create_ai_generation_governance(
    body: CreateGenerationGovernanceEntryRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor_tenant_id = UUID(principal.tenant_id)
    if body.is_global:
        if body.tenant_id is not None:
            raise _api_error(status.HTTP_404_NOT_FOUND, "governance_tenant_not_found")
        tenant_id: UUID | None = None
    else:
        tenant_id = body.tenant_id or actor_tenant_id
        if tenant_id != actor_tenant_id:
            raise _api_error(status.HTTP_404_NOT_FOUND, "governance_tenant_not_found")

    existing = session.scalar(
        select(GenerationGovernanceEntry).where(
            GenerationGovernanceEntry.is_global.is_(body.is_global),
            GenerationGovernanceEntry.target_type == body.target_type,
            GenerationGovernanceEntry.target_key == body.target_key,
            GenerationGovernanceEntry.tenant_id.is_(tenant_id)
            if body.is_global
            else GenerationGovernanceEntry.tenant_id == tenant_id,
        )
    )
    if existing is not None:
        raise _api_error(status.HTTP_409_CONFLICT, "governance_entry_duplicate")
    entry = GenerationGovernanceEntry(
        tenant_id=tenant_id,
        is_global=body.is_global,
        target_type=body.target_type,
        target_key=body.target_key,
        control_state=body.control_state,
        note=body.note,
        created_by_user_id=UUID(principal.user_id),
    )
    session.add(entry)
    session.flush()
    append_audit_event(
        session,
        tenant_id=actor_tenant_id,
        actor_user_id=UUID(principal.user_id),
        event_type="ai_generation_governance.entry_created",
        target_type="generation_governance_entry",
        target_id=entry.id,
        metadata={
            "is_global": body.is_global,
            "target_type": body.target_type.value,
            "target_key": body.target_key,
            "control_state": body.control_state.value,
        },
    )
    return _governance_entry_payload(entry)


@router.post("/ai-generation-governance/{entry_id}/transition")
def transition_ai_generation_governance_entry(
    entry_id: UUID,
    body: TransitionGenerationGovernanceEntryRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor_tenant_id = UUID(principal.tenant_id)
    entry = _admin_governance_entry(session, entry_id=entry_id, tenant_id=actor_tenant_id)
    if entry is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "governance_entry_not_found")
    previous_state = entry.control_state
    try:
        assert_transition_is_valid(entry.control_state, body.control_state)
    except ValueError as exc:
        raise _api_error(status.HTTP_409_CONFLICT, "invalid_governance_transition") from exc
    entry.control_state = body.control_state
    session.flush()
    append_audit_event(
        session,
        tenant_id=actor_tenant_id,
        actor_user_id=UUID(principal.user_id),
        event_type="ai_generation_governance.entry_transitioned",
        target_type="generation_governance_entry",
        target_id=entry.id,
        metadata={
            "target_type": entry.target_type.value,
            "target_key": entry.target_key,
            "from": previous_state.value,
            "to": body.control_state.value,
        },
    )
    return _governance_entry_payload(entry)


def _admin_governance_entry(
    session: Session, *, entry_id: UUID, tenant_id: UUID
) -> GenerationGovernanceEntry | None:
    return session.scalar(
        select(GenerationGovernanceEntry).where(
            GenerationGovernanceEntry.id == entry_id,
            or_(
                GenerationGovernanceEntry.is_global.is_(True),
                and_(
                    GenerationGovernanceEntry.is_global.is_(False),
                    GenerationGovernanceEntry.tenant_id == tenant_id,
                ),
            ),
        )
    )


def _governance_entry_payload(entry: GenerationGovernanceEntry) -> dict[str, object]:
    return {
        "id": str(entry.id),
        "is_global": entry.is_global,
        "tenant_id": str(entry.tenant_id) if entry.tenant_id is not None else None,
        "target_type": entry.target_type.value,
        "target_key": entry.target_key,
        "control_state": entry.control_state.value,
        "note": entry.note,
        "created_at": entry.created_at.isoformat(),
        "updated_at": entry.updated_at.isoformat(),
    }


def _api_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})
