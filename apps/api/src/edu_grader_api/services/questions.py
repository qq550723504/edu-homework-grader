from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Question, QuestionVersion, VersionStatus


class QuestionVersionAccessError(PermissionError):
    """Raised when an actor is not allowed to modify a question version."""


class QuestionVersionStateError(ValueError):
    """Raised when an operation is invalid for the version lifecycle state."""


def create_successor_draft(
    session: Session,
    published_version: QuestionVersion,
    *,
    actor_user_id: UUID,
) -> QuestionVersion:
    """Copy a published version into the next immutable-history draft."""

    _require_author(session, published_version, actor_user_id)
    if published_version.status is not VersionStatus.PUBLISHED:
        raise QuestionVersionStateError("only published versions can have a successor draft")

    latest_version_number = session.scalar(
        select(func.max(QuestionVersion.version_number)).where(
            QuestionVersion.question_id == published_version.question_id
        )
    )
    successor = QuestionVersion(
        question_id=published_version.question_id,
        version_number=(latest_version_number or 0) + 1,
        status=VersionStatus.DRAFT,
        prompt=published_version.prompt,
        question_type=published_version.question_type,
        grading_policy_id=published_version.grading_policy_id,
        rule_json=published_version.rule_json.copy(),
        created_by_user_id=actor_user_id,
    )
    session.add(successor)
    return successor


def update_draft(
    session: Session,
    draft: QuestionVersion,
    *,
    actor_user_id: UUID,
    prompt: str,
) -> None:
    """Update mutable draft content without allowing history rewrites."""

    _require_author(session, draft, actor_user_id)
    if draft.status is not VersionStatus.DRAFT:
        raise QuestionVersionStateError("only draft versions can be edited")
    draft.prompt = prompt
    session.add(draft)


def _require_author(session: Session, version: QuestionVersion, actor_user_id: UUID) -> None:
    author_id = session.scalar(
        select(Question.created_by_user_id).where(Question.id == version.question_id)
    )
    if author_id != actor_user_id:
        raise QuestionVersionAccessError("only the original author can edit this question")
