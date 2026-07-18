from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import ReviewAction, ReviewReason, Role
from ..services.reviews import (
    ReviewAccessError,
    ReviewConflictError,
    ReviewValidationError,
    batch_confirm_deterministic,
    decide_review_task,
    get_teacher_review_task,
    list_teacher_review_tasks,
    publish_attempt_results,
)


router = APIRouter(prefix="/v1/review-tasks", tags=["teacher reviews"])
publication_router = APIRouter(prefix="/v1/assignments", tags=["grade publication"])


class ReviewDecisionRequest(BaseModel):
    action: ReviewAction
    version: int = Field(ge=0)
    score: float | None = None
    reason: str | None = Field(default=None, max_length=2_000)


class BatchConfirmRequest(BaseModel):
    task_ids: list[UUID] = Field(min_length=1)


@router.get("")
def list_review_tasks_route(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    class_id: UUID | None = None,
    assignment_id: UUID | None = None,
    subject: str | None = None,
    question_type: str | None = None,
    reason: Annotated[ReviewReason | None, Query()] = None,
) -> dict[str, list[dict[str, object]]]:
    tasks = list_teacher_review_tasks(
        session,
        tenant_id=UUID(principal.tenant_id),
        teacher_id=UUID(principal.user_id),
        class_id=class_id,
        assignment_id=assignment_id,
        subject=subject,
        question_type=question_type,
        reason=reason,
    )
    return {
        "review_tasks": [
            {
                "assignment_id": str(task.attempt_answer.attempt.assignment_id),
                "attempt_id": str(task.attempt_answer.attempt_id),
                "assignment_item_id": str(task.attempt_answer.assignment_item_id),
                "reason": task.reason.value,
                "question_type": task.attempt_answer.assignment_item.question_version.question_type,
                "version": task.version,
            }
            for task in tasks
        ]
    }


@router.get("/{task_id}")
def get_review_task_route(
    task_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        task = get_teacher_review_task(
            session,
            tenant_id=UUID(principal.tenant_id),
            teacher_id=UUID(principal.user_id),
            task_id=task_id,
        )
    except ReviewAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    run = task.grading_run
    return {
        "id": str(task.id),
        "reason": task.reason.value,
        "status": task.status.value,
        "version": task.version,
        "answer": task.attempt_answer.answer_json,
        "rule_snapshot": run.rule_snapshot_json,
        "grading": {
            "decision": run.decision,
            "score": run.score,
            "max_score": run.max_score,
            "confidence": run.confidence,
            "requires_review": run.requires_review,
            "evidence": run.evidence_json,
        },
        "signals": [
            {
                "kind": signal.kind,
                "code": signal.code,
                "passed": signal.passed,
                "score": signal.score,
                "max_score": signal.max_score,
                "evidence": signal.evidence_json,
            }
            for signal in run.signals
        ],
        "decisions": [
            {
                "action": decision.action.value,
                "original_score": decision.original_score,
                "final_score": decision.final_score,
                "reason": decision.reason,
                "task_version": decision.task_version,
                "created_at": decision.created_at.isoformat(),
            }
            for decision in task.decisions
        ],
    }


@router.post("/{task_id}/decisions", status_code=status.HTTP_201_CREATED)
def decide_review_task_route(
    task_id: UUID,
    body: ReviewDecisionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            decision = decide_review_task(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                task_id=task_id,
                action=body.action,
                version=body.version,
                score=body.score,
                reason=body.reason,
            )
    except ReviewAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except ReviewConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="review task changed"
        ) from None
    except ReviewValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    return {
        "id": str(decision.id),
        "action": decision.action.value,
        "original_score": decision.original_score,
        "final_score": decision.final_score,
        "task_version": decision.task_version,
    }


@router.post("/batch-confirm", status_code=status.HTTP_201_CREATED)
def batch_confirm_route(
    assignment_id: UUID,
    body: BatchConfirmRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, object]]]:
    try:
        session.rollback()
        with session.begin():
            decisions = batch_confirm_deterministic(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                assignment_id=assignment_id,
                task_ids=body.task_ids,
            )
    except ReviewAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except ReviewConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="task is not batch eligible"
        ) from None
    return {
        "decisions": [
            {"id": str(decision.id), "action": decision.action.value} for decision in decisions
        ]
    }


@publication_router.post(
    "/{assignment_id}/attempts/{attempt_id}/publish-results", status_code=status.HTTP_201_CREATED
)
def publish_attempt_results_route(
    assignment_id: UUID,
    attempt_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            publication = publish_attempt_results(
                session,
                tenant_id=UUID(principal.tenant_id),
                teacher_id=UUID(principal.user_id),
                assignment_id=assignment_id,
                attempt_id=attempt_id,
            )
    except ReviewAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except ReviewConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="attempt is not publishable"
        ) from None
    return {"id": str(publication.id), "status": "published"}
