from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..models import (
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    AttemptAnswer,
    AttemptStatus,
    AuditLog,
    ClassTeacher,
    Classroom,
    Enrollment,
    Question,
    QuestionVersion,
    StudentAttempt,
    SubmissionReceipt,
    VersionStatus,
    utc_now,
)


class AssignmentAccessError(Exception):
    """Raised when a teacher cannot access an assignment resource."""


class AssignmentStateError(Exception):
    """Raised when an assignment transition is invalid."""


class AssignmentValidationError(Exception):
    """Raised when assignment input cannot form a valid published selection."""


class AnswerConflictError(Exception):
    def __init__(self, answer: AttemptAnswer) -> None:
        self.answer = answer


class SubmissionConflictError(Exception):
    """Raised when a submission key or attempt cannot be submitted."""


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


def list_student_assignments(
    session: Session, *, tenant_id: UUID, student_id: UUID
) -> dict[str, list[Assignment]]:
    assignments = list(
        session.scalars(
            select(Assignment)
            .join(Enrollment, Enrollment.class_id == Assignment.class_id)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.status == AssignmentStatus.PUBLISHED,
                Enrollment.student_id == student_id,
            )
            .order_by(Assignment.due_at, Assignment.id)
        )
    )
    grouped: dict[str, list[Assignment]] = {
        "pending": [],
        "correction_required": [],
        "completed": [],
    }
    for assignment in assignments:
        attempt = session.scalar(
            select(StudentAttempt).where(
                StudentAttempt.assignment_id == assignment.id,
                StudentAttempt.student_id == student_id,
                StudentAttempt.attempt_number == 1,
            )
        )
        grouped[
            "completed" if attempt and attempt.status is AttemptStatus.SUBMITTED else "pending"
        ].append(assignment)
    return grouped


def get_student_assignment(
    session: Session, *, tenant_id: UUID, student_id: UUID, assignment_id: UUID
) -> tuple[Assignment, StudentAttempt]:
    assignment = session.scalar(
        select(Assignment)
        .join(Enrollment, Enrollment.class_id == Assignment.class_id)
        .where(
            Assignment.id == assignment_id,
            Assignment.tenant_id == tenant_id,
            Assignment.status == AssignmentStatus.PUBLISHED,
            Enrollment.student_id == student_id,
        )
    )
    if assignment is None:
        raise AssignmentAccessError()
    attempt = session.scalar(
        select(StudentAttempt).where(
            StudentAttempt.assignment_id == assignment.id,
            StudentAttempt.student_id == student_id,
            StudentAttempt.attempt_number == 1,
        )
    )
    if attempt is None:
        attempt = StudentAttempt(
            tenant_id=tenant_id,
            assignment=assignment,
            student_id=student_id,
            attempt_number=1,
        )
        session.add(attempt)
        session.flush()
    return assignment, attempt


def save_answer(
    session: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    attempt_id: UUID,
    assignment_item_id: UUID,
    answer_json: dict[str, object],
    expected_version: int,
) -> AttemptAnswer:
    attempt = session.scalar(
        select(StudentAttempt)
        .join(Assignment)
        .join(Enrollment, Enrollment.class_id == Assignment.class_id)
        .where(
            StudentAttempt.id == attempt_id,
            StudentAttempt.tenant_id == tenant_id,
            StudentAttempt.student_id == student_id,
            StudentAttempt.status == AttemptStatus.DRAFT,
            Enrollment.student_id == student_id,
        )
    )
    item = session.scalar(
        select(AssignmentItem).where(
            AssignmentItem.id == assignment_item_id,
            AssignmentItem.assignment_id == attempt.assignment_id if attempt else False,
        )
    )
    if attempt is None or item is None:
        raise AssignmentAccessError()
    answer = session.scalar(
        select(AttemptAnswer).where(
            AttemptAnswer.attempt_id == attempt_id,
            AttemptAnswer.assignment_item_id == assignment_item_id,
        )
    )
    if answer is None:
        if expected_version != 0:
            raise AssignmentStateError("answer version is stale")
        answer = AttemptAnswer(
            attempt=attempt,
            assignment_item=item,
            answer_json=answer_json,
            version=1,
        )
        session.add(answer)
        session.flush()
        return answer
    updated = session.execute(
        update(AttemptAnswer)
        .where(AttemptAnswer.id == answer.id, AttemptAnswer.version == expected_version)
        .values(answer_json=answer_json, version=expected_version + 1, updated_at=utc_now())
    )
    if updated.rowcount != 1:
        session.refresh(answer)
        raise AnswerConflictError(answer)
    session.flush()
    session.refresh(answer)
    return answer


def submit_attempt(
    session: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    assignment_id: UUID,
    idempotency_key: str,
) -> tuple[int, dict[str, object]]:
    assignment, attempt = get_student_assignment(
        session, tenant_id=tenant_id, student_id=student_id, assignment_id=assignment_id
    )
    fingerprint = f"assignment:{assignment.id}:attempt:{attempt.id}"
    receipt = session.scalar(
        select(SubmissionReceipt).where(
            SubmissionReceipt.student_id == student_id,
            SubmissionReceipt.idempotency_key == idempotency_key,
        )
    )
    if receipt is not None:
        if receipt.assignment_id != assignment_id or receipt.request_fingerprint != fingerprint:
            raise SubmissionConflictError("idempotency key belongs to another submission")
        return receipt.response_status, receipt.response_json
    if attempt.status is not AttemptStatus.DRAFT:
        raise SubmissionConflictError("attempt has already been submitted")
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = utc_now()
    response = {"attempt_id": str(attempt.id), "status": AttemptStatus.SUBMITTED.value}
    session.add(
        SubmissionReceipt(
            tenant_id=tenant_id,
            student_id=student_id,
            assignment_id=assignment_id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            response_status=200,
            response_json=response,
        )
    )
    _audit(
        session,
        tenant_id=tenant_id,
        actor_user_id=student_id,
        event_type="student_attempt.submitted",
        target_type="student_attempt",
        target_id=attempt.id,
        metadata={"assignment_id": str(assignment_id)},
    )
    return 200, response


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
