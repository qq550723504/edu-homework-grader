from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import AssignmentItem, AttemptAnswer, Role
from ..services.assignments import (
    AssignmentAccessError,
    AnswerConflictError,
    AssignmentStateError,
    AssignmentValidationError,
    add_assignment_item,
    create_assignment,
    get_teacher_assignment,
    get_student_assignment,
    list_student_assignments,
    publish_assignment,
    save_answer,
    SubmissionConflictError,
    submit_attempt,
)


router = APIRouter(prefix="/v1/assignments", tags=["assignments"])
student_router = APIRouter(prefix="/v1/student", tags=["student assignments"])


class CreateAssignmentRequest(BaseModel):
    class_id: UUID
    title: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=30)
    due_at: datetime
    submission_rule: dict[str, object]


class AddAssignmentItemRequest(BaseModel):
    question_version_id: UUID
    position: int = Field(ge=1)


class SaveAnswerRequest(BaseModel):
    answer: dict[str, object]
    version: int = Field(ge=0)


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


@student_router.get("/assignments")
def list_student_assignments_route(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.STUDENT))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, str]]]:
    grouped = list_student_assignments(
        session, tenant_id=UUID(principal.tenant_id), student_id=UUID(principal.user_id)
    )
    return {
        key: [_assignment_summary(assignment) for assignment in value]
        for key, value in grouped.items()
    }


@student_router.get("/assignments/{assignment_id}")
def get_student_assignment_route(
    assignment_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.STUDENT))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            assignment, attempt = get_student_assignment(
                session,
                tenant_id=UUID(principal.tenant_id),
                student_id=UUID(principal.user_id),
                assignment_id=assignment_id,
            )
            answers = {
                answer.assignment_item_id: answer
                for answer in session.scalars(
                    select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)
                )
            }
            items = list(
                session.scalars(
                    select(AssignmentItem)
                    .where(AssignmentItem.assignment_id == assignment.id)
                    .order_by(AssignmentItem.position)
                )
            )
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    return {
        **_assignment_summary(assignment),
        "attempt": {"id": str(attempt.id), "status": attempt.status.value},
        "items": [
            {
                "id": str(item.id),
                "question_version_id": str(item.question_version_id),
                "position": item.position,
                "answer": answers[item.id].answer_json if item.id in answers else None,
                "version": answers[item.id].version if item.id in answers else 0,
            }
            for item in items
        ],
    }


@student_router.put("/attempts/{attempt_id}/answers/{assignment_item_id}")
def save_answer_route(
    attempt_id: UUID,
    assignment_item_id: UUID,
    body: SaveAnswerRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.STUDENT))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            answer = save_answer(
                session,
                tenant_id=UUID(principal.tenant_id),
                student_id=UUID(principal.user_id),
                attempt_id=attempt_id,
                assignment_item_id=assignment_item_id,
                answer_json=body.answer,
                expected_version=body.version,
            )
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except AnswerConflictError as error:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "current": {"answer": error.answer.answer_json, "version": error.answer.version}
            },
        )
    except AssignmentStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"answer": answer.answer_json, "version": answer.version}


@student_router.post("/assignments/{assignment_id}/submit")
def submit_assignment_route(
    assignment_id: UUID,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    principal: CurrentPrincipal = Depends(require_role(Role.STUDENT)),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    if idempotency_key is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key is required"
        )
    try:
        key = str(UUID(idempotency_key))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Idempotency-Key is invalid"
        ) from None
    try:
        session.rollback()
        with session.begin():
            _, response = submit_attempt(
                session,
                tenant_id=UUID(principal.tenant_id),
                student_id=UUID(principal.user_id),
                assignment_id=assignment_id,
                idempotency_key=key,
            )
    except AssignmentAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except SubmissionConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return response


def _assignment_summary(assignment) -> dict[str, str]:
    return {
        "id": str(assignment.id),
        "title": assignment.title,
        "subject": assignment.subject,
        "due_at": assignment.due_at.isoformat(),
        "status": assignment.status.value,
    }
