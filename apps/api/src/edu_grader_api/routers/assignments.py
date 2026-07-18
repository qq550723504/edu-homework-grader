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
from ..services.assignments import (
    AssignmentAccessError,
    AssignmentStateError,
    AssignmentValidationError,
    add_assignment_item,
    create_assignment,
    get_teacher_assignment,
    publish_assignment,
)


router = APIRouter(prefix="/v1/assignments", tags=["assignments"])


class CreateAssignmentRequest(BaseModel):
    class_id: UUID
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=30)
    due_at: datetime
    submission_rule: dict[str, object]


class AddAssignmentItemRequest(BaseModel):
    question_version_id: UUID
    position: int = Field(ge=1)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_assignment_route(
    body: CreateAssignmentRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            assignment = create_assignment(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                class_id=body.class_id,
                title=body.title,
                subject=body.subject,
                due_at=body.due_at,
                submission_rule_json=body.submission_rule,
            )
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    return {"id": str(assignment.id), "status": assignment.status.value}


@router.post("/{assignment_id}/items", status_code=status.HTTP_201_CREATED)
def add_assignment_item_route(
    assignment_id: UUID,
    body: AddAssignmentItemRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | int]:
    try:
        session.rollback()
        with session.begin():
            assignment = get_teacher_assignment(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                assignment_id=assignment_id,
            )
            item = add_assignment_item(
                session,
                assignment,
                teacher_id=UUID(principal.user_id),
                question_version_id=body.question_version_id,
                position=body.position,
            )
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except AssignmentStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except AssignmentValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return {"id": str(item.id), "position": item.position}


@router.post("/{assignment_id}/publish")
def publish_assignment_route(
    assignment_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            assignment = get_teacher_assignment(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                assignment_id=assignment_id,
            )
            published = publish_assignment(session, assignment, teacher_id=UUID(principal.user_id))
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except AssignmentStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"id": str(published.id), "status": published.status.value}
