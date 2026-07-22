from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID

from edu_generator.contracts import GeneratedCandidate, ProviderFailure
from edu_generator.openai_provider import OpenAIResponsesProvider
from edu_generator.providers import FakeGenerationProvider, GenerationProvider
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_any_role
from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GeneratedQuestionReviewDecision,
    GenerationJob,
    GenerationValidationRun,
    Role,
    User,
)
from ..services.ai_question_review import (
    ReviewAccessError,
    ReviewConflictError,
    ReviewStateError,
    accept_review_draft,
    create_review_revision,
    reject_review_draft,
)
from ..services.generation import (
    GenerationJobRequest,
    GenerationServiceError,
    cancel_generation_job,
    create_or_get_job,
    run_generation_job,
)
from ..services.grader import HttpGraderClient
from ..settings import settings


router = APIRouter(prefix="/v1/ai-question-generation", tags=["AI question generation"])
draft_router = APIRouter(prefix="/v1/ai-generated-questions", tags=["AI question generation"])


class CreateGenerationJobRequest(BaseModel):
    curriculum_objective_revision_id: UUID
    grade: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=100)
    question_types: list[Literal["M1", "M2", "E1", "E2", "E3", "E4"]] = Field(
        min_length=1, max_length=20
    )
    requested_count: int = Field(ge=1, le=20)
    policy_catalog_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)


class RegenerateDraftRequest(BaseModel):
    teacher_constraint: str | None = Field(default=None, max_length=1_000)


class CreateReviewRevisionRequest(BaseModel):
    expected_revision_number: int = Field(ge=1)
    candidate: GeneratedCandidate


class RejectReviewDraftRequest(BaseModel):
    expected_revision_number: int = Field(ge=1)
    reason: Literal[
        "incorrect_answer",
        "out_of_scope",
        "unclear_wording",
        "duplicate",
        "unsuitable_for_students",
        "other",
    ]
    detail: str | None = Field(default=None, max_length=500)


class AcceptReviewDraftRequest(BaseModel):
    expected_revision_number: int = Field(ge=1)
    confirm_warnings: bool = False


@router.post("/jobs", status_code=status.HTTP_201_CREATED)
def create_generation_job_route(
    body: CreateGenerationJobRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "idempotency_key_required")
    actor = _actor(session, principal)
    request = GenerationJobRequest(
        **body.model_dump(),
        idempotency_key=idempotency_key,
    )
    existing = _find_job_by_idempotency(session, actor=actor, idempotency_key=idempotency_key)
    if existing is None:
        _enforce_generation_quota(session, actor=actor, requested_count=request.requested_count)
    try:
        job = create_or_get_job(session, request=request, actor=actor)
        created = existing is None
        if created:
            session.commit()
            run_generation_job(
                session,
                job=job,
                provider=_generation_provider(),
                teacher_constraint=request.teacher_constraint,
            )
            append_audit_event(
                session,
                tenant_id=job.tenant_id,
                actor_user_id=actor.id,
                event_type="ai_generation.completed",
                target_type="generation_job",
                target_id=job.id,
                metadata={
                    "status": job.status.value,
                    "requested_count": job.requested_count,
                    "succeeded_count": job.succeeded_count,
                    "provider": _provider_name(),
                },
            )
        session.commit()
    except GenerationServiceError as exc:
        session.rollback()
        raise _api_error(status.HTTP_409_CONFLICT, "generation_request_rejected") from exc
    except ProviderFailure as exc:
        session.rollback()
        raise _api_error(status.HTTP_503_SERVICE_UNAVAILABLE, exc.code) from exc
    return _job_payload(job)


@router.get("/jobs")
def list_generation_jobs_route(
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=20, ge=1, le=100),
    after: UUID | None = None,
) -> dict[str, object]:
    actor = _actor(session, principal)
    statement = select(GenerationJob).where(GenerationJob.tenant_id == actor.tenant_id)
    if actor.role is Role.TEACHER:
        statement = statement.where(GenerationJob.teacher_user_id == actor.id)
    if after is not None:
        after_job = _authorized_job(session, job_id=after, actor=actor)
        statement = statement.where(
            or_(
                GenerationJob.created_at < after_job.created_at,
                and_(
                    GenerationJob.created_at == after_job.created_at,
                    GenerationJob.id < after_job.id,
                ),
            )
        )
    jobs = session.scalars(
        statement.order_by(GenerationJob.created_at.desc(), GenerationJob.id.desc()).limit(
            limit + 1
        )
    ).all()
    items = jobs[:limit]
    return {
        "items": [_job_payload(job) for job in items],
        "next_after": str(items[-1].id) if len(jobs) > limit else None,
    }


@router.get("/jobs/{job_id}")
def get_generation_job_route(
    job_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor = _actor(session, principal)
    return _job_payload(_authorized_job(session, job_id=job_id, actor=actor))


@router.get("/jobs/{job_id}/questions")
def list_generated_questions_route(
    job_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=20, ge=1, le=100),
    after: UUID | None = None,
) -> dict[str, object]:
    actor = _actor(session, principal)
    job = _authorized_job(session, job_id=job_id, actor=actor)
    statement = select(GeneratedQuestionDraft).where(GeneratedQuestionDraft.job_id == job.id)
    if after is not None:
        after_draft = session.get(GeneratedQuestionDraft, after)
        if after_draft is None or after_draft.job_id != job.id:
            raise _api_error(status.HTTP_404_NOT_FOUND, "generation_draft_not_found")
        statement = statement.where(GeneratedQuestionDraft.ordinal > after_draft.ordinal)
    drafts = session.scalars(
        statement.order_by(GeneratedQuestionDraft.ordinal).limit(limit + 1)
    ).all()
    items = drafts[:limit]
    return {
        "items": [_draft_payload(draft) for draft in items],
        "next_after": str(items[-1].id) if len(drafts) > limit else None,
    }


@router.post("/jobs/{job_id}/cancel")
def cancel_generation_job_route(
    job_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor = _actor(session, principal)
    job = _authorized_job(session, job_id=job_id, actor=actor)
    try:
        cancel_generation_job(session, job=job)
        session.commit()
    except GenerationServiceError as exc:
        session.rollback()
        raise _api_error(status.HTTP_409_CONFLICT, "generation_cancel_rejected") from exc
    return _job_payload(job)


@draft_router.post("/{draft_id}/regenerate", status_code=status.HTTP_201_CREATED)
def regenerate_draft_route(
    draft_id: UUID,
    body: RegenerateDraftRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    if not idempotency_key:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "idempotency_key_required")
    actor = _actor(session, principal)
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor)
    original = draft.job
    question_type = draft.candidate_json.get("question_type")
    if not isinstance(question_type, str):
        raise _api_error(status.HTTP_409_CONFLICT, "generation_draft_invalid")
    request = GenerationJobRequest(
        curriculum_objective_revision_id=original.curriculum_objective_revision_id,
        grade=original.grade or "unspecified",
        subject=original.subject or "unspecified",
        question_types=[question_type],
        requested_count=1,
        idempotency_key=idempotency_key,
        policy_catalog_version=original.policy_version or "unknown",
        prompt_version=original.prompt_version or "unknown",
        teacher_constraint=body.teacher_constraint,
    )
    existing = _find_job_by_idempotency(session, actor=actor, idempotency_key=idempotency_key)
    if existing is None:
        _enforce_generation_quota(session, actor=actor, requested_count=1)
    try:
        job = create_or_get_job(session, request=request, actor=actor)
        if existing is None:
            session.commit()
            run_generation_job(
                session,
                job=job,
                provider=_generation_provider(),
                teacher_constraint=body.teacher_constraint,
            )
            append_audit_event(
                session,
                tenant_id=job.tenant_id,
                actor_user_id=actor.id,
                event_type="ai_generation.regenerated",
                target_type="generation_job",
                target_id=job.id,
                metadata={"source_draft_id": str(draft.id), "status": job.status.value},
            )
        session.commit()
    except GenerationServiceError as exc:
        session.rollback()
        raise _api_error(status.HTTP_409_CONFLICT, "generation_request_rejected") from exc
    except ProviderFailure as exc:
        session.rollback()
        raise _api_error(status.HTTP_503_SERVICE_UNAVAILABLE, exc.code) from exc
    return _job_payload(job)


@draft_router.post("/{draft_id}/revisions", status_code=status.HTTP_201_CREATED)
def create_review_revision_route(
    draft_id: UUID,
    body: CreateReviewRevisionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    key = _required_idempotency_key(idempotency_key)
    actor = _actor(session, principal)
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor, for_update=True)
    digest = _request_digest("revision", body)
    replay = _replayed_revision(
        session,
        draft=draft,
        idempotency_key=key,
        request_digest=digest,
    )
    if replay is not None:
        return replay
    try:
        result = create_review_revision(
            session,
            draft,
            actor,
            body.expected_revision_number,
            body.candidate.model_dump(mode="json"),
            HttpGraderClient(settings.grader_base_url),
            idempotency_key=key,
            request_digest=digest,
        )
        session.commit()
    except (IntegrityError, ReviewConflictError) as exc:
        session.rollback()
        replay = _recover_revision_replay(
            session,
            draft_id=draft_id,
            actor=actor,
            idempotency_key=key,
            request_digest=digest,
        )
        if replay is not None:
            return replay
        if isinstance(exc, ReviewConflictError):
            raise _review_error(exc) from exc
        raise _api_error(status.HTTP_409_CONFLICT, "review_write_conflict") from exc
    except (ReviewStateError, ReviewAccessError) as exc:
        session.rollback()
        raise _review_error(exc) from exc
    return _revision_payload(result.revision, result.validation_run)


@draft_router.post("/{draft_id}/reject")
def reject_review_draft_route(
    draft_id: UUID,
    body: RejectReviewDraftRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    key = _required_idempotency_key(idempotency_key)
    actor = _actor(session, principal)
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor, for_update=True)
    digest = _request_digest("reject", body)
    replay = _replayed_decision(
        session,
        draft=draft,
        action="reject",
        idempotency_key=key,
        request_digest=digest,
    )
    if replay is not None:
        return replay
    try:
        decision = reject_review_draft(
            session,
            draft,
            actor,
            body.expected_revision_number,
            body.reason,
            body.detail,
            idempotency_key=key,
            request_digest=digest,
        )
        session.commit()
    except (IntegrityError, ReviewConflictError) as exc:
        session.rollback()
        replay = _recover_decision_replay(
            session,
            draft_id=draft_id,
            actor=actor,
            action="reject",
            idempotency_key=key,
            request_digest=digest,
        )
        if replay is not None:
            return replay
        if isinstance(exc, ReviewConflictError):
            raise _review_error(exc) from exc
        raise _api_error(status.HTTP_409_CONFLICT, "review_write_conflict") from exc
    except (ReviewStateError, ReviewAccessError) as exc:
        session.rollback()
        raise _review_error(exc) from exc
    return _decision_payload(decision)


@draft_router.post("/{draft_id}/accept")
def accept_review_draft_route(
    draft_id: UUID,
    body: AcceptReviewDraftRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    key = _required_idempotency_key(idempotency_key)
    actor = _actor(session, principal)
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor, for_update=True)
    digest = _request_digest("accept", body)
    replay = _replayed_decision(
        session,
        draft=draft,
        action="accept",
        idempotency_key=key,
        request_digest=digest,
    )
    if replay is not None:
        return replay
    try:
        result = accept_review_draft(
            session,
            draft,
            actor,
            body.expected_revision_number,
            body.confirm_warnings,
            idempotency_key=key,
            request_digest=digest,
        )
        session.commit()
    except (IntegrityError, ReviewConflictError) as exc:
        session.rollback()
        replay = _recover_decision_replay(
            session,
            draft_id=draft_id,
            actor=actor,
            action="accept",
            idempotency_key=key,
            request_digest=digest,
        )
        if replay is not None:
            return replay
        if isinstance(exc, ReviewConflictError):
            raise _review_error(exc) from exc
        raise _api_error(status.HTTP_409_CONFLICT, "review_write_conflict") from exc
    except (ReviewStateError, ReviewAccessError) as exc:
        session.rollback()
        raise _review_error(exc) from exc
    return _decision_payload(result.decision)


def _generation_provider() -> GenerationProvider:
    if settings.generation_provider == "fake":
        return FakeGenerationProvider(seed=0)
    if settings.generation_provider == "openai":
        return OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            model=settings.generator_openai_model,
            base_url=settings.generator_openai_base_url,
            allowed_hosts=settings.allowed_generator_provider_hosts,
            timeout_seconds=settings.generator_timeout_seconds,
        )
    raise ProviderFailure("provider_not_configured", "generation provider is not configured")


def _provider_name() -> str:
    return settings.generation_provider


def _actor(session: Session, principal: CurrentPrincipal) -> User:
    actor = session.get(User, UUID(principal.user_id))
    if actor is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "generation_actor_not_found")
    return actor


def _authorized_job(session: Session, *, job_id: UUID, actor: User) -> GenerationJob:
    statement = select(GenerationJob).where(
        GenerationJob.id == job_id,
        GenerationJob.tenant_id == actor.tenant_id,
    )
    if actor.role is Role.TEACHER:
        statement = statement.where(GenerationJob.teacher_user_id == actor.id)
    job = session.scalar(statement)
    if job is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "generation_job_not_found")
    return job


def _authorized_draft(
    session: Session,
    *,
    draft_id: UUID,
    actor: User,
    for_update: bool = False,
) -> GeneratedQuestionDraft:
    statement = (
        select(GeneratedQuestionDraft)
        .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
        .where(
            GeneratedQuestionDraft.id == draft_id,
            GenerationJob.tenant_id == actor.tenant_id,
        )
    )
    if actor.role is Role.TEACHER:
        statement = statement.where(GenerationJob.teacher_user_id == actor.id)
    if for_update:
        statement = statement.with_for_update(of=GeneratedQuestionDraft).execution_options(
            populate_existing=True
        )
    draft = session.scalar(statement)
    if draft is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "generation_draft_not_found")
    return draft


def _find_job_by_idempotency(
    session: Session, *, actor: User, idempotency_key: str
) -> GenerationJob | None:
    job = session.scalar(
        select(GenerationJob).where(
            GenerationJob.tenant_id == actor.tenant_id,
            GenerationJob.idempotency_key == idempotency_key,
        )
    )
    if job is not None and job.teacher_user_id != actor.id:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_key_conflict")
    return job


def _required_idempotency_key(value: str | None) -> str:
    if value is None or not value.strip() or len(value) > 128:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "idempotency_key_required")
    return value


def _request_digest(action: str, body: BaseModel) -> str:
    serialized = json.dumps(
        {"action": action, "body": body.model_dump(mode="json")},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(serialized.encode()).hexdigest()


def _replayed_revision(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    idempotency_key: str,
    request_digest: str,
) -> dict[str, object] | None:
    conflicting_decision = session.scalar(
        select(GeneratedQuestionReviewDecision).where(
            GeneratedQuestionReviewDecision.generated_question_draft_id == draft.id,
            GeneratedQuestionReviewDecision.idempotency_key == idempotency_key,
        )
    )
    if conflicting_decision is not None:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_key_conflict")
    revision = session.scalar(
        select(GeneratedQuestionDraftRevision).where(
            GeneratedQuestionDraftRevision.generated_question_draft_id == draft.id,
            GeneratedQuestionDraftRevision.idempotency_key == idempotency_key,
        )
    )
    if revision is None:
        return None
    if revision.request_digest != request_digest:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_key_conflict")
    validation_run = session.scalar(
        select(GenerationValidationRun)
        .where(
            GenerationValidationRun.generated_question_draft_id == draft.id,
            GenerationValidationRun.draft_revision_id == revision.id,
        )
        .order_by(GenerationValidationRun.run_number.asc())
        .limit(1)
    )
    if validation_run is None:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_replay_unavailable")
    return _revision_payload(revision, validation_run)


def _replayed_decision(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    action: str,
    idempotency_key: str,
    request_digest: str,
) -> dict[str, object] | None:
    conflicting_revision = session.scalar(
        select(GeneratedQuestionDraftRevision).where(
            GeneratedQuestionDraftRevision.generated_question_draft_id == draft.id,
            GeneratedQuestionDraftRevision.idempotency_key == idempotency_key,
        )
    )
    if conflicting_revision is not None:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_key_conflict")
    decision = session.scalar(
        select(GeneratedQuestionReviewDecision).where(
            GeneratedQuestionReviewDecision.generated_question_draft_id == draft.id,
            GeneratedQuestionReviewDecision.idempotency_key == idempotency_key,
        )
    )
    if decision is None:
        return None
    if decision.action != action or decision.request_digest != request_digest:
        raise _api_error(status.HTTP_409_CONFLICT, "idempotency_key_conflict")
    return _decision_payload(decision)


def _recover_revision_replay(
    session: Session,
    *,
    draft_id: UUID,
    actor: User,
    idempotency_key: str,
    request_digest: str,
) -> dict[str, object] | None:
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor)
    return _replayed_revision(
        session,
        draft=draft,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )


def _recover_decision_replay(
    session: Session,
    *,
    draft_id: UUID,
    actor: User,
    action: str,
    idempotency_key: str,
    request_digest: str,
) -> dict[str, object] | None:
    draft = _authorized_draft(session, draft_id=draft_id, actor=actor)
    return _replayed_decision(
        session,
        draft=draft,
        action=action,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )


def _enforce_generation_quota(session: Session, *, actor: User, requested_count: int) -> None:
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if requested_count > settings.generator_max_batch_size:
        raise _api_error(status.HTTP_422_UNPROCESSABLE_CONTENT, "generation_batch_limit_exceeded")
    used = session.scalar(
        select(func.coalesce(func.sum(GenerationJob.requested_count), 0)).where(
            GenerationJob.tenant_id == actor.tenant_id,
            GenerationJob.created_at >= today,
        )
    )
    if int(used or 0) + requested_count > settings.generator_daily_tenant_limit:
        raise _api_error(status.HTTP_429_TOO_MANY_REQUESTS, "generation_quota_exceeded")


def _job_payload(job: GenerationJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status.value,
        "requested_count": job.requested_count,
        "succeeded_count": job.succeeded_count,
        "failed_count": job.failed_count,
        "failure_code": job.failure_code,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _draft_payload(draft: GeneratedQuestionDraft) -> dict[str, object]:
    return {
        "id": str(draft.id),
        "ordinal": draft.ordinal,
        "teacher_state": draft.teacher_state,
        "candidate": draft.candidate_json,
        "validation_errors": draft.validation_errors_json or [],
    }


def _revision_payload(
    revision: GeneratedQuestionDraftRevision,
    validation_run: GenerationValidationRun,
) -> dict[str, object]:
    return {
        "draft_id": str(revision.generated_question_draft_id),
        "revision_number": revision.revision_number,
        "validation_run": _public_validation_run_payload(validation_run),
    }


def _decision_payload(decision: GeneratedQuestionReviewDecision) -> dict[str, object]:
    return {
        "draft_id": str(decision.generated_question_draft_id),
        "action": decision.action,
        "revision_number": decision.draft_revision.revision_number,
        "validation_run": _public_validation_run_payload(decision.validation_run),
        "accepted_question_version_id": (
            str(decision.accepted_question_version_id)
            if decision.accepted_question_version_id is not None
            else None
        ),
    }


def _public_validation_run_payload(run: GenerationValidationRun) -> dict[str, object]:
    # Imported lazily to keep the authorization dependency one-way while sharing one safe projection.
    from .ai_question_validation import _run_payload

    return _run_payload(run)


def _review_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReviewAccessError):
        return _api_error(status.HTTP_404_NOT_FOUND, "generation_draft_not_found")
    return _api_error(status.HTTP_409_CONFLICT, str(exc))


def _api_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})
