"""Append-only teacher review workflow for AI-generated question candidates."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping
from uuid import uuid4

from edu_generator.contracts import GeneratedCandidate
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GeneratedQuestionReviewDecision,
    GenerationJob,
    GenerationValidationRun,
    QuestionVersion,
    Role,
    User,
    ValidationRunStatus,
)
from ..settings import settings
from .grader import HttpGraderClient
from .question_verification import VerificationGraderClient, run_candidate_verification
from .questions import create_question


_REJECTION_REASONS = frozenset(
    {
        "incorrect_answer",
        "out_of_scope",
        "unclear_wording",
        "duplicate",
        "unsuitable_for_students",
        "other",
    }
)


class ReviewConflictError(RuntimeError):
    """Raised when optimistic concurrency or the review state changed."""


class ReviewStateError(ValueError):
    """Raised when a requested review transition is invalid."""


class ReviewAccessError(PermissionError):
    """Raised when an actor cannot review the candidate's generation job."""


@dataclass(frozen=True)
class ReviewRevisionResult:
    revision: GeneratedQuestionDraftRevision
    validation_run: GenerationValidationRun


@dataclass(frozen=True)
class AcceptedReviewResult:
    decision: GeneratedQuestionReviewDecision
    question_version: QuestionVersion


def create_review_revision(
    session: Session,
    draft: GeneratedQuestionDraft,
    actor: User,
    expected_revision_number: int,
    candidate: Mapping[str, object],
    grader_client: VerificationGraderClient,
    *,
    idempotency_key: str | None = None,
    request_digest: str | None = None,
) -> ReviewRevisionResult:
    """Append a teacher edit and synchronously verify the immutable revision."""

    locked_draft, current_revision = _lock_pending_review(
        session,
        draft=draft,
        actor=actor,
        expected_revision_number=expected_revision_number,
    )
    validated = GeneratedCandidate.model_validate(dict(candidate))
    content = validated.model_dump(mode="json")
    _require_same_candidate_identity(locked_draft.candidate_json, content)
    digest = request_digest or _content_hash(content)
    revision = GeneratedQuestionDraftRevision(
        generated_question_draft_id=locked_draft.id,
        revision_number=current_revision.revision_number + 1,
        candidate_json=content,
        content_hash=_content_hash(content),
        editor_user_id=actor.id,
        idempotency_key=idempotency_key or f"service-{uuid4()}",
        request_digest=digest,
    )
    session.add(revision)
    session.flush()
    locked_draft.current_revision_id = revision.id
    session.flush()
    validation_run = run_candidate_verification(
        session,
        draft=locked_draft,
        revision=revision,
        grader_client=grader_client,
    )
    append_audit_event(
        session,
        tenant_id=locked_draft.job.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_question_review.revised",
        target_type="generated_question_draft",
        target_id=locked_draft.id,
        metadata={
            "revision_number": revision.revision_number,
            "validation_run_id": validation_run.id,
            "validation_status": validation_run.status.value,
        },
    )
    return ReviewRevisionResult(revision=revision, validation_run=validation_run)


def reject_review_draft(
    session: Session,
    draft: GeneratedQuestionDraft,
    actor: User,
    expected_revision_number: int,
    reason: str,
    detail: str | None,
    *,
    idempotency_key: str | None = None,
    request_digest: str | None = None,
) -> GeneratedQuestionReviewDecision:
    """Reject a candidate while retaining validation evidence for the decision."""

    normalized_detail = _validate_rejection(reason, detail)
    locked_draft, current_revision = _lock_pending_review(
        session,
        draft=draft,
        actor=actor,
        expected_revision_number=expected_revision_number,
    )
    validation_run = _latest_current_validation_run(
        session,
        draft=locked_draft,
        revision=current_revision,
        for_update=True,
    )
    if validation_run is None:
        validation_run = run_candidate_verification(
            session,
            draft=locked_draft,
            revision=current_revision,
            grader_client=_default_grader_client(),
        )
    persisted_reason = reason if reason != "other" else f"other: {normalized_detail}"
    digest = request_digest or _content_hash(
        {
            "action": "reject",
            "revision_number": current_revision.revision_number,
            "reason": reason,
            "detail": normalized_detail,
        }
    )
    decision = GeneratedQuestionReviewDecision(
        generated_question_draft_id=locked_draft.id,
        draft_revision_id=current_revision.id,
        generation_validation_run_id=validation_run.id,
        action="reject",
        reason=persisted_reason,
        warning_confirmed=False,
        actor_user_id=actor.id,
        idempotency_key=idempotency_key or f"service-{uuid4()}",
        request_digest=digest,
    )
    session.add(decision)
    locked_draft.teacher_state = "rejected"
    append_audit_event(
        session,
        tenant_id=locked_draft.job.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_question_review.rejected",
        target_type="generated_question_draft",
        target_id=locked_draft.id,
        metadata={
            "revision_number": current_revision.revision_number,
            "validation_run_id": validation_run.id,
            "reason_code": reason,
        },
    )
    session.flush()
    return decision


def accept_review_draft(
    session: Session,
    draft: GeneratedQuestionDraft,
    actor: User,
    expected_revision_number: int,
    confirm_warnings: bool,
    *,
    idempotency_key: str | None = None,
    request_digest: str | None = None,
) -> AcceptedReviewResult:
    """Accept a verified candidate into the existing mutable question-draft flow."""

    locked_draft, current_revision = _lock_pending_review(
        session,
        draft=draft,
        actor=actor,
        expected_revision_number=expected_revision_number,
    )
    latest_run = _latest_validation_run(session, draft=locked_draft, for_update=True)
    if latest_run is None:
        raise ReviewStateError("validation_missing")
    if latest_run.draft_revision_id != current_revision.id:
        raise ReviewStateError("validation_stale")
    if latest_run.status is ValidationRunStatus.BLOCKED:
        raise ReviewStateError("validation_blocked")
    if latest_run.status is ValidationRunStatus.WARNING and not confirm_warnings:
        raise ReviewStateError("warning_confirmation_required")

    candidate = GeneratedCandidate.model_validate(current_revision.candidate_json)
    question_version = create_question(
        session,
        tenant_id=locked_draft.job.tenant_id,
        actor_user_id=actor.id,
        title=f"AI {candidate.question_type} candidate {locked_draft.ordinal}",
        prompt=candidate.prompt,
        question_type=candidate.question_type,
        policy_version=candidate.policy_version,
        rule_json=candidate.rule_json,
        reading_material=candidate.reading_material,
    )
    session.flush()
    digest = request_digest or _content_hash(
        {
            "action": "accept",
            "revision_number": current_revision.revision_number,
            "confirm_warnings": confirm_warnings,
        }
    )
    decision = GeneratedQuestionReviewDecision(
        generated_question_draft_id=locked_draft.id,
        draft_revision_id=current_revision.id,
        generation_validation_run_id=latest_run.id,
        action="accept",
        reason=None,
        warning_confirmed=confirm_warnings,
        actor_user_id=actor.id,
        accepted_question_version_id=question_version.id,
        idempotency_key=idempotency_key or f"service-{uuid4()}",
        request_digest=digest,
    )
    session.add(decision)
    locked_draft.teacher_state = "accepted"
    append_audit_event(
        session,
        tenant_id=locked_draft.job.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_question_review.accepted",
        target_type="generated_question_draft",
        target_id=locked_draft.id,
        metadata={
            "revision_number": current_revision.revision_number,
            "validation_run_id": latest_run.id,
            "question_version_id": question_version.id,
        },
    )
    session.flush()
    return AcceptedReviewResult(decision=decision, question_version=question_version)


def _lock_pending_review(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    actor: User,
    expected_revision_number: int,
) -> tuple[GeneratedQuestionDraft, GeneratedQuestionDraftRevision]:
    session.flush()
    locked_draft = session.scalar(
        select(GeneratedQuestionDraft)
        .where(GeneratedQuestionDraft.id == draft.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_draft is None:
        raise ReviewConflictError("review_draft_missing")
    _require_review_access(session, draft=locked_draft, actor=actor)
    if locked_draft.teacher_state != "pending_review":
        raise ReviewConflictError("review_state_conflict")
    current_revision = session.scalar(
        select(GeneratedQuestionDraftRevision)
        .where(
            GeneratedQuestionDraftRevision.id == locked_draft.current_revision_id,
            GeneratedQuestionDraftRevision.generated_question_draft_id == locked_draft.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if current_revision is None:
        raise ReviewStateError("current_revision_missing")
    if current_revision.revision_number != expected_revision_number:
        raise ReviewConflictError("review_revision_conflict")
    return locked_draft, current_revision


def _require_review_access(session: Session, *, draft: GeneratedQuestionDraft, actor: User) -> None:
    job = session.get(GenerationJob, draft.job_id)
    if actor.role not in {Role.TEACHER, Role.ADMIN}:
        raise ReviewAccessError("review_access_denied")
    if job is None or actor.tenant_id != job.tenant_id:
        raise ReviewAccessError("review_access_denied")
    if actor.role is Role.TEACHER and actor.id != job.teacher_user_id:
        raise ReviewAccessError("review_access_denied")


def _latest_validation_run(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    for_update: bool,
) -> GenerationValidationRun | None:
    statement = (
        select(GenerationValidationRun)
        .where(GenerationValidationRun.generated_question_draft_id == draft.id)
        .order_by(GenerationValidationRun.run_number.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement.execution_options(populate_existing=True))


def _latest_current_validation_run(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    for_update: bool,
) -> GenerationValidationRun | None:
    statement = (
        select(GenerationValidationRun)
        .where(
            GenerationValidationRun.generated_question_draft_id == draft.id,
            GenerationValidationRun.draft_revision_id == revision.id,
        )
        .order_by(GenerationValidationRun.run_number.desc())
        .limit(1)
    )
    if for_update:
        statement = statement.with_for_update()
    return session.scalar(statement.execution_options(populate_existing=True))


def _require_same_candidate_identity(
    original: Mapping[str, object], candidate: Mapping[str, object]
) -> None:
    for field in ("objective_revision_id", "question_type", "policy_version"):
        if str(candidate.get(field)) != str(original.get(field)):
            raise ReviewStateError("candidate_identity_changed")


def _validate_rejection(reason: str, detail: str | None) -> str | None:
    if reason not in _REJECTION_REASONS:
        raise ReviewStateError("invalid_rejection_reason")
    normalized_detail = detail.strip() if isinstance(detail, str) else None
    if reason == "other" and (
        normalized_detail is None or not normalized_detail or len(normalized_detail) > 500
    ):
        raise ReviewStateError("rejection_detail_required")
    return normalized_detail


def _content_hash(content: object) -> str:
    serialized = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return sha256(serialized.encode()).hexdigest()


def _default_grader_client() -> VerificationGraderClient:
    return HttpGraderClient(settings.grader_base_url)
