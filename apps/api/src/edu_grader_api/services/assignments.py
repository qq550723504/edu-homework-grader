from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    AuditLog,
    ClassTeacher,
    Classroom,
    Question,
    QuestionVersion,
    VersionStatus,
    utc_now,
)


class AssignmentAccessError(Exception):
    """Raised when a teacher cannot access an assignment resource."""


class AssignmentStateError(Exception):
    """Raised when an assignment transition is invalid."""


class AssignmentValidationError(Exception):
    """Raised when assignment input cannot form a valid published selection."""


def create_assignment(
    session: Session,
    *,
    tenant_id: UUID,
    teacher_id: UUID,
    class_id: UUID,
    title: str,
    subject: str,
    due_at: datetime,
    submission_rule_json: dict[str, object],
) -> Assignment:
    classroom = _assigned_classroom(
        session, tenant_id=tenant_id, teacher_id=teacher_id, class_id=class_id
    )
    assignment = Assignment(
        tenant_id=tenant_id,
        classroom=classroom,
        created_by_user_id=teacher_id,
        title=title,
        subject=subject,
        due_at=due_at,
        submission_rule_json=submission_rule_json,
    )
    session.add(assignment)
    session.flush()
    _audit(
        session,
        tenant_id=tenant_id,
        actor_user_id=teacher_id,
        event_type="assignment.created",
        target_type="assignment",
        target_id=assignment.id,
        metadata={"class_id": str(class_id)},
    )
    return assignment


def add_assignment_item(
    session: Session,
    assignment: Assignment,
    *,
    teacher_id: UUID,
    question_version_id: UUID,
    position: int,
) -> AssignmentItem:
    _require_assignment_teacher(session, assignment, teacher_id)
    if assignment.status is not AssignmentStatus.DRAFT:
        raise AssignmentStateError("only draft assignments can add items")

    question_version = session.scalar(
        select(QuestionVersion)
        .join(Question)
        .where(
            QuestionVersion.id == question_version_id,
            QuestionVersion.status == VersionStatus.PUBLISHED,
            Question.tenant_id == assignment.tenant_id,
        )
    )
    if question_version is None:
        raise AssignmentValidationError("assignment items must use tenant-local published versions")

    item = AssignmentItem(
        assignment=assignment,
        question_version=question_version,
        position=position,
    )
    session.add(item)
    session.flush()
    _audit(
        session,
        tenant_id=assignment.tenant_id,
        actor_user_id=teacher_id,
        event_type="assignment.item_added",
        target_type="assignment",
        target_id=assignment.id,
        metadata={"assignment_item_id": str(item.id), "position": position},
    )
    return item


def publish_assignment(session: Session, assignment: Assignment, *, teacher_id: UUID) -> Assignment:
    _require_assignment_teacher(session, assignment, teacher_id)
    if assignment.status is not AssignmentStatus.DRAFT:
        raise AssignmentStateError("only draft assignments can be published")
    if not session.scalar(
        select(AssignmentItem.id).where(AssignmentItem.assignment_id == assignment.id).limit(1)
    ):
        raise AssignmentStateError("an assignment requires at least one item")

    assignment.status = AssignmentStatus.PUBLISHED
    assignment.published_at = utc_now()
    session.add(assignment)
    _audit(
        session,
        tenant_id=assignment.tenant_id,
        actor_user_id=teacher_id,
        event_type="assignment.published",
        target_type="assignment",
        target_id=assignment.id,
        metadata={},
    )
    return assignment


def get_teacher_assignment(
    session: Session, *, tenant_id: UUID, teacher_id: UUID, assignment_id: UUID
) -> Assignment:
    assignment = session.scalar(
        select(Assignment).where(Assignment.id == assignment_id, Assignment.tenant_id == tenant_id)
    )
    if assignment is None:
        raise AssignmentAccessError()
    _require_assignment_teacher(session, assignment, teacher_id)
    return assignment


def _assigned_classroom(
    session: Session, *, tenant_id: UUID, teacher_id: UUID, class_id: UUID
) -> Classroom:
    classroom = session.scalar(
        select(Classroom).where(Classroom.id == class_id, Classroom.tenant_id == tenant_id)
    )
    if classroom is None or session.get(ClassTeacher, (class_id, teacher_id)) is None:
        raise AssignmentAccessError()
    return classroom


def _require_assignment_teacher(session: Session, assignment: Assignment, teacher_id: UUID) -> None:
    _assigned_classroom(
        session,
        tenant_id=assignment.tenant_id,
        teacher_id=teacher_id,
        class_id=assignment.class_id,
    )


def _audit(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    event_type: str,
    target_type: str,
    target_id: UUID,
    metadata: dict[str, object],
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata,
        )
    )
