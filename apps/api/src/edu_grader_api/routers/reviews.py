from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import ReviewReason, Role
from ..services.reviews import list_teacher_review_tasks


router = APIRouter(prefix="/v1/review-tasks", tags=["teacher reviews"])


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
