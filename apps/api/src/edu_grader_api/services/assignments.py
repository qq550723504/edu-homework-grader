from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..answer_envelope import AnswerEnvelopeValidationError, normalize_answer_envelope
from ..audit import append_audit_event
from ..models import (
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    AttemptAnswer,
    AttemptStatus,
    ClassTeacher,
    CorrectionAttempt,
    Classroom,
    Enrollment,
    GradePublication,
    GradingRun,
    GradingSignal,
    Question,
    QuestionVersion,
    StudentAttempt,
    SubmissionReceipt,
    VersionStatus,
    utc_now,
)
from ..settings import settings
from .grader import HttpGraderClient, MathAnswerNormalizationError
from .questions import GradeResult
from .reviews import create_review_task_for_run


class AssignmentAccessError(Exception):
    """Raised when a teacher cannot access an assignment resource."""


class AssignmentStateError(Exception):
    """Raised when an assignment transition is invalid."""


class AssignmentDeadlineError(AssignmentStateError):
    code = "assignment_overdue"


class AssignmentValidationError(Exception):
    """Raised when assignment input cannot form a valid published selection."""


class AnswerConflictError(Exception):
    def __init__(self, answer: AttemptAnswer) -> None:
        self.answer = answer


class SubmissionConflictError(Exception):
    """Raised when a submission key or attempt cannot be submitted."""


class MathAnswerValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


SUBJECT_QUESTION_TYPES = {
    "english": frozenset({"E1", "E2", "E3", "E4"}),
    "mathematics": frozenset({"M1", "M2"}),
}


class MathAnswerNormalizer(Protocol):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]: ...


class SubmissionGraderClient(Protocol):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult: ...


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
    question_version_ids: list[UUID],
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
    replace_assignment_items(
        session,
        assignment,
        teacher_id=teacher_id,
        question_version_ids=question_version_ids,
    )
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


def replace_assignment_items(
    session: Session,
    assignment: Assignment,
    *,
    teacher_id: UUID,
    question_version_ids: list[UUID],
) -> list[AssignmentItem]:
    """Replace a draft's ordered items after validating its complete composition."""

    _require_assignment_teacher(session, assignment, teacher_id)
    if assignment.status is not AssignmentStatus.DRAFT:
        raise AssignmentStateError("only draft assignments can change items")
    versions = _composition_versions(session, assignment, question_version_ids)
    session.execute(delete(AssignmentItem).where(AssignmentItem.assignment_id == assignment.id))
    items = [
        AssignmentItem(assignment=assignment, question_version=version, position=position)
        for position, version in enumerate(versions, start=1)
    ]
    session.add_all(items)
    session.flush()
    return items


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

    question_version = _composition_versions(session, assignment, [question_version_id])[0]
    if (
        session.scalar(
            select(AssignmentItem.id).where(
                AssignmentItem.assignment_id == assignment.id,
                AssignmentItem.question_version_id == question_version_id,
            )
        )
        is not None
    ):
        raise AssignmentValidationError("assignment items cannot repeat a question version")
    expected_position = (
        session.scalar(
            select(func.count(AssignmentItem.id)).where(
                AssignmentItem.assignment_id == assignment.id
            )
        )
        or 0
    ) + 1
    if position != expected_position:
        raise AssignmentValidationError("assignment item positions must be continuous")

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


def _composition_versions(
    session: Session, assignment: Assignment, question_version_ids: list[UUID]
) -> list[QuestionVersion]:
    allowed_types = SUBJECT_QUESTION_TYPES.get(assignment.subject)
    if allowed_types is None:
        raise AssignmentValidationError("unsupported assignment subject")
    if not question_version_ids:
        raise AssignmentValidationError("an assignment requires at least one item")
    if len(set(question_version_ids)) != len(question_version_ids):
        raise AssignmentValidationError("assignment items cannot repeat a question version")
    versions = list(
        session.scalars(
            select(QuestionVersion)
            .join(Question)
            .where(
                QuestionVersion.id.in_(question_version_ids),
                QuestionVersion.status == VersionStatus.PUBLISHED,
                Question.tenant_id == assignment.tenant_id,
            )
        )
    )
    by_id = {version.id: version for version in versions}
    if len(by_id) != len(question_version_ids):
        raise AssignmentValidationError("assignment items must use tenant-local published versions")
    ordered_versions = [by_id[version_id] for version_id in question_version_ids]
    if any(version.question_type not in allowed_types for version in ordered_versions):
        raise AssignmentValidationError("assignment subject does not match question types")
    return ordered_versions


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
) -> dict[str, list[tuple[Assignment, str]]]:
    assignments = list(
        session.scalars(
            select(Assignment)
            .join(Enrollment, Enrollment.class_id == Assignment.class_id)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.status == AssignmentStatus.PUBLISHED,
                Enrollment.student_id == student_id,
            )
            .order_by(Assignment.due_at, Assignment.created_at, Assignment.id)
        )
    )
    grouped: dict[str, list[tuple[Assignment, str]]] = {
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
        correction_pending = None
        if attempt is not None:
            correction_pending = session.scalar(
                select(CorrectionAttempt.id)
                .join(
                    StudentAttempt,
                    CorrectionAttempt.correction_attempt_id == StudentAttempt.id,
                )
                .outerjoin(GradePublication, GradePublication.attempt_id == StudentAttempt.id)
                .where(
                    CorrectionAttempt.original_attempt_id == attempt.id,
                    GradePublication.id.is_(None),
                )
                .limit(1)
            )
        if correction_pending is not None:
            grouped["correction_required"].append((assignment, "correction_required"))
            continue
        if attempt is not None and attempt.status is AttemptStatus.SUBMITTED:
            published = session.scalar(
                select(GradePublication.id)
                .where(GradePublication.attempt_id == attempt.id)
                .limit(1)
            )
            if published is not None:
                grouped["completed"].append((assignment, "completed"))
            else:
                grouped["pending"].append((assignment, "submitted_pending_review"))
        else:
            if _is_assignment_late(assignment):
                status = (
                    "late_allowed"
                    if assignment.submission_rule_json.get("allow_late") is True
                    else "overdue"
                )
                grouped["pending"].append((assignment, status))
            else:
                grouped["pending"].append((assignment, "pending"))
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
    answer_normalizer: MathAnswerNormalizer | None = None,
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
    _enforce_assignment_deadline(attempt.assignment)
    stored_answer = _normalize_answer_if_needed(
        item,
        answer_json,
        answer_normalizer or HttpGraderClient(settings.grader_base_url),
    )
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
            answer_json=stored_answer,
            version=1,
        )
        session.add(answer)
        session.flush()
        return answer
    updated = session.execute(
        update(AttemptAnswer)
        .where(AttemptAnswer.id == answer.id, AttemptAnswer.version == expected_version)
        .values(answer_json=stored_answer, version=expected_version + 1, updated_at=utc_now())
    )
    if updated.rowcount != 1:
        session.refresh(answer)
        raise AnswerConflictError(answer)
    session.flush()
    session.refresh(answer)
    return answer


def _normalize_answer_if_needed(
    item: AssignmentItem,
    answer_json: dict[str, object],
    answer_normalizer: MathAnswerNormalizer,
) -> dict[str, object]:
    expected_format = "mathjson-v1" if _is_mathjson_item(item) else "text-v1"
    try:
        envelope = normalize_answer_envelope(answer_json, expected_format=expected_format)
    except AnswerEnvelopeValidationError as error:
        raise MathAnswerValidationError(error.code, str(error)) from error
    if expected_format == "text-v1":
        return envelope
    variables = item.question_version.rule_json.get("variables", [])
    try:
        ast = answer_normalizer.normalize_math_answer(
            {"mathjson": envelope["mathjson"], "variables": variables}
        )
    except MathAnswerNormalizationError as error:
        raise MathAnswerValidationError(error.code, str(error)) from error
    return {
        "format": "mathjson-v1",
        "latex": envelope["latex"],
        "mathjson": envelope["mathjson"],
        "ast": ast,
    }


def is_mathjson_item(item: AssignmentItem) -> bool:
    return _is_mathjson_item(item)


def _is_mathjson_item(item: AssignmentItem) -> bool:
    version = item.question_version
    return (
        version.question_type == "M2"
        and version.grading_policy is not None
        and version.grading_policy.policy_version == "2"
    )


def submit_attempt(
    session: Session,
    *,
    tenant_id: UUID,
    student_id: UUID,
    assignment_id: UUID,
    idempotency_key: str,
    attempt_id: UUID | None = None,
    grader_client: SubmissionGraderClient | None = None,
) -> tuple[int, dict[str, object]]:
    assignment, default_attempt = get_student_assignment(
        session, tenant_id=tenant_id, student_id=student_id, assignment_id=assignment_id
    )
    attempt = default_attempt
    if attempt_id is not None:
        attempt = session.scalar(
            select(StudentAttempt)
            .join(Assignment, StudentAttempt.assignment_id == Assignment.id)
            .join(Enrollment, Enrollment.class_id == Assignment.class_id)
            .where(
                StudentAttempt.id == attempt_id,
                StudentAttempt.tenant_id == tenant_id,
                StudentAttempt.assignment_id == assignment_id,
                StudentAttempt.student_id == student_id,
                Enrollment.student_id == student_id,
            )
        )
        if (
            attempt is None
            or session.scalar(
                select(CorrectionAttempt.id).where(
                    CorrectionAttempt.correction_attempt_id == attempt.id
                )
            )
            is None
        ):
            raise AssignmentAccessError()
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
    submitted_late = _is_assignment_late(assignment)
    _enforce_assignment_deadline(assignment)
    grading = _grade_attempt(
        session,
        assignment=assignment,
        attempt=attempt,
        grader_client=grader_client or HttpGraderClient(settings.grader_base_url),
    )
    attempt.status = AttemptStatus.SUBMITTED
    attempt.submitted_at = utc_now()
    response = {
        "attempt_id": str(attempt.id),
        "status": AttemptStatus.SUBMITTED.value,
        "grading": grading,
    }
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
        metadata={"assignment_id": str(assignment_id), "submitted_late": submitted_late},
    )
    return 200, response


def _enforce_assignment_deadline(assignment: Assignment) -> None:
    if assignment.submission_rule_json.get("allow_late") is True:
        return
    if _is_assignment_late(assignment):
        raise AssignmentDeadlineError("assignment is past its deadline")


def _is_assignment_late(assignment: Assignment) -> bool:
    due_at = assignment.due_at
    if due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=timezone.utc)
    return utc_now() > due_at


def _grade_attempt(
    session: Session,
    *,
    assignment: Assignment,
    attempt: StudentAttempt,
    grader_client: SubmissionGraderClient,
) -> list[dict[str, object]]:
    items = list(
        session.scalars(
            select(AssignmentItem)
            .where(AssignmentItem.assignment_id == assignment.id)
            .order_by(AssignmentItem.position)
        )
    )
    answers = {
        answer.assignment_item_id: answer
        for answer in session.scalars(
            select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt.id)
        )
    }
    response: list[dict[str, object]] = []
    for item in items:
        answer = answers.get(item.id)
        if answer is None:
            answer = AttemptAnswer(
                attempt=attempt,
                assignment_item=item,
                answer_json={"format": "text-v1", "text": ""},
                version=1,
            )
            session.add(answer)
            session.flush()
        version = item.question_version
        policy = version.grading_policy
        policy_version = policy.policy_version if policy is not None else None
        try:
            result = grader_client.grade(
                version.question_type,
                version.rule_json,
                answer.answer_json,
                policy_version=policy_version,
            )
        except Exception as error:  # Dependency errors must remain visible and reviewable.
            result = _dependency_review_result(version.rule_json, error)
        run = _persist_grading_run(session, answer=answer, item=item, result=result)
        create_review_task_for_run(session, run)
        response.append(_student_grading_summary(item, run))
    return response


def _dependency_review_result(rule: dict[str, object], error: Exception) -> GradeResult:
    max_score = rule.get("max_score", 1)
    if isinstance(max_score, bool) or not isinstance(max_score, int | float) or max_score <= 0:
        max_score = 1
    return GradeResult(
        decision="needs_review",
        score=0.0,
        grader_version="grader-unavailable",
        evidence={
            "max_score": float(max_score),
            "confidence": 0.0,
            "criteria": [
                {
                    "code": "grader_dependency",
                    "score": 0.0,
                    "max_score": float(max_score),
                    "passed": False,
                    "evidence": str(error),
                }
            ],
            "feedback": [{"type": "dependency", "message": "批改服务暂不可用，已转人工复核。"}],
            "signals": [{"kind": "dependency", "message": str(error)}],
            "requires_review": True,
            "dependency_versions": {"grader": "unavailable"},
        },
    )


def _persist_grading_run(
    session: Session,
    *,
    answer: AttemptAnswer,
    item: AssignmentItem,
    result: GradeResult,
) -> GradingRun:
    evidence = deepcopy(result.evidence)
    max_score = _evidence_number(evidence, "max_score", default=1.0)
    confidence = _evidence_number(evidence, "confidence", default=0.0)
    requires_review = evidence.get("requires_review") is True
    dependency_versions = evidence.get("dependency_versions")
    signals = evidence.get("signals")
    rule = item.question_version.rule_json
    threshold = rule.get("similarity_threshold")
    thresholds = {"similarity": threshold} if isinstance(threshold, int | float) else {}
    run = GradingRun(
        attempt_answer=answer,
        question_version_id=item.question_version_id,
        grading_policy_id=item.question_version.grading_policy_id,
        policy_version=(
            item.question_version.grading_policy.policy_version
            if item.question_version.grading_policy is not None
            else "unavailable"
        ),
        rule_snapshot_json=deepcopy(rule),
        answer_snapshot_json=deepcopy(answer.answer_json),
        decision=result.decision,
        score=result.score,
        max_score=max_score,
        confidence=confidence,
        requires_review=requires_review,
        grader_version=result.grader_version,
        dependency_versions_json=(
            deepcopy(dependency_versions) if isinstance(dependency_versions, dict) else {}
        ),
        thresholds_json=thresholds,
        evidence_json=evidence,
    )
    session.add(run)
    for ordinal, signal in enumerate(_signals_from_evidence(evidence, signals)):
        run.signals.append(signal)
        signal.ordinal = ordinal
    session.flush()
    return run


def _signals_from_evidence(evidence: dict[str, object], signals: object) -> list[GradingSignal]:
    rows: list[GradingSignal] = []
    criteria = evidence.get("criteria")
    if isinstance(criteria, list):
        for criterion in criteria:
            if isinstance(criterion, dict):
                rows.append(
                    GradingSignal(
                        kind="criterion",
                        code=criterion.get("code")
                        if isinstance(criterion.get("code"), str)
                        else None,
                        passed=criterion.get("passed")
                        if isinstance(criterion.get("passed"), bool)
                        else None,
                        score=_optional_number(criterion.get("score")),
                        max_score=_optional_number(criterion.get("max_score")),
                        evidence_json=deepcopy(criterion),
                    )
                )
    if isinstance(signals, list):
        for signal in signals:
            if isinstance(signal, dict):
                rows.append(
                    GradingSignal(
                        kind=signal.get("kind")
                        if isinstance(signal.get("kind"), str)
                        else "signal",
                        code=signal.get("code") if isinstance(signal.get("code"), str) else None,
                        passed=None,
                        score=None,
                        max_score=None,
                        evidence_json=deepcopy(signal),
                    )
                )
    feedback = evidence.get("feedback")
    if isinstance(feedback, list):
        for item in feedback:
            if isinstance(item, dict):
                rows.append(
                    GradingSignal(
                        kind="feedback",
                        code=item.get("rule_id") if isinstance(item.get("rule_id"), str) else None,
                        passed=None,
                        score=None,
                        max_score=None,
                        evidence_json=deepcopy(item),
                    )
                )
    return rows


def _evidence_number(evidence: dict[str, object], key: str, *, default: float) -> float:
    value = evidence.get(key)
    return (
        float(value) if isinstance(value, int | float) and not isinstance(value, bool) else default
    )


def _optional_number(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _student_grading_summary(item: AssignmentItem, run: GradingRun) -> dict[str, object]:
    feedback = run.evidence_json.get("feedback")
    return {
        "assignment_item_id": str(item.id),
        "requires_review": run.requires_review,
        "feedback": deepcopy(feedback) if isinstance(feedback, list) else [],
    }


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
    append_audit_event(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
    )
