from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from edu_generator.contracts import GeneratedCandidate, GenerationRequest, ProviderFailure
from edu_generator.prompt_templates import PromptTemplate, resolve_prompt_template
from edu_generator.providers import GenerationProvider
from edu_grader_processor_policy import (
    ProcessorPolicyError,
    assert_deidentified_payload,
    assert_deidentified_text,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumObjectiveRevision,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    Role,
    User,
    utc_now,
)
from ..policies import validate_policy


class GenerationServiceError(ValueError):
    """Stable service-layer error safe for API responses and audit metadata."""


GENERATION_POLICY_CATALOG_VERSION = "2026.07"
GENERATION_PROMPT_VERSION = "generator-v1"


class GenerationJobRequest(BaseModel):
    """Bounded, de-identified teacher request for candidate generation."""

    model_config = ConfigDict(extra="forbid")

    curriculum_objective_revision_id: UUID
    question_types: list[Literal["M1", "M2", "E1", "E2", "E3", "E4"]] = Field(
        min_length=1, max_length=20
    )
    requested_count: int = Field(ge=1, le=20)
    idempotency_key: str = Field(min_length=1, max_length=128)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)

    def model_post_init(self, __context: object) -> None:
        try:
            assert_deidentified_payload(self.model_dump(mode="json"))
        except ValueError as exc:
            raise ValueError("generation requests must be de-identified") from exc


@dataclass(frozen=True, slots=True)
class GenerationJobSnapshot:
    """Server-owned generation metadata persisted with a job."""

    grade: str
    subject: str
    policy_catalog_version: str
    prompt_version: str

    @classmethod
    def from_job(cls, job: GenerationJob) -> GenerationJobSnapshot:
        return cls(
            grade=job.grade or "unspecified",
            subject=job.subject or "unspecified",
            policy_catalog_version=job.policy_version or "unknown",
            prompt_version=job.prompt_version or "unknown",
        )


def create_or_get_job(
    session: Session,
    *,
    request: GenerationJobRequest,
    actor: User,
    snapshot: GenerationJobSnapshot | None = None,
) -> GenerationJob:
    """Create a tenant-scoped job or safely replay its exact idempotency key."""

    if actor.role not in {Role.TEACHER, Role.ADMIN}:
        raise GenerationServiceError("only teachers and administrators can generate candidates")
    request_digest = _request_digest(request)
    existing = session.scalar(
        select(GenerationJob).where(
            GenerationJob.tenant_id == actor.tenant_id,
            GenerationJob.idempotency_key == request.idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_digest != request_digest:
            raise GenerationServiceError("idempotency key belongs to another generation request")
        return existing

    revision = session.get(CurriculumObjectiveRevision, request.curriculum_objective_revision_id)
    if revision is None:
        raise GenerationServiceError("curriculum objective revision was not found")
    if (
        revision.status is not CurriculumRevisionStatus.ACTIVE
        or revision.objective.status is not CurriculumProfileStatus.ACTIVE
        or revision.objective.profile.status is not CurriculumProfileStatus.ACTIVE
    ):
        raise GenerationServiceError("curriculum objective revision must be active")
    if not set(request.question_types).issubset(set(revision.allowed_question_types)):
        raise GenerationServiceError("requested question types are not allowed by the objective")
    if len(request.question_types) != request.requested_count:
        raise GenerationServiceError("generation_distribution_invalid")
    active_snapshot = snapshot or _snapshot_from_active_revision(revision)
    try:
        resolve_prompt_template(active_snapshot.prompt_version, request.question_types)
    except ValueError as exc:
        raise GenerationServiceError("prompt template is not available for this request") from exc

    job = GenerationJob(
        tenant_id=actor.tenant_id,
        teacher_user_id=actor.id,
        curriculum_profile_id=revision.objective.profile_id,
        curriculum_objective_revision_id=revision.id,
        grade=active_snapshot.grade,
        subject=active_snapshot.subject,
        distribution_json={"question_types": request.question_types},
        requested_count=request.requested_count,
        status=GenerationJobStatus.QUEUED,
        idempotency_key=request.idempotency_key,
        policy_version=active_snapshot.policy_catalog_version,
        prompt_version=active_snapshot.prompt_version,
        request_digest=request_digest,
    )
    session.add(job)
    session.flush()
    return job


def _snapshot_from_active_revision(revision: CurriculumObjectiveRevision) -> GenerationJobSnapshot:
    grade_mapping = revision.objective.grade_mapping
    if grade_mapping is None:
        raise GenerationServiceError("curriculum objective revision requires a grade mapping")
    return GenerationJobSnapshot(
        grade=grade_mapping.internal_level,
        subject=revision.objective.subject,
        policy_catalog_version=GENERATION_POLICY_CATALOG_VERSION,
        prompt_version=GENERATION_PROMPT_VERSION,
    )


def run_generation_job(
    session: Session,
    *,
    job: GenerationJob,
    provider: GenerationProvider,
    teacher_constraint: str | None = None,
    max_attempts: int = 2,
) -> GenerationJob:
    """Run a bounded generation attempt without publishing any question version."""

    if max_attempts < 1 or max_attempts > 2:
        raise ValueError("generation retries must be between one and two attempts")
    if job.status is GenerationJobStatus.CANCELLED or job.cancel_requested_at is not None:
        job.status = GenerationJobStatus.CANCELLED
        job.finished_at = utc_now()
        session.flush()
        return job
    if job.status in {GenerationJobStatus.READY_FOR_REVIEW, GenerationJobStatus.PARTIALLY_FAILED}:
        return job

    request = _provider_request(session, job, teacher_constraint=teacher_constraint)
    try:
        template = resolve_prompt_template(request.prompt_version, request.question_types)
    except ValueError:
        job.status = GenerationJobStatus.FAILED
        job.failure_code = "prompt_template_unavailable"
        job.failed_count = max(job.requested_count - job.succeeded_count, 0)
        job.finished_at = utc_now()
        session.flush()
        return job
    job.status = GenerationJobStatus.GENERATING
    job.started_at = job.started_at or utc_now()
    session.flush()

    for attempt_number in range(len(job.attempts) + 1, max_attempts + 1):
        attempt = GenerationAttempt(
            job_id=job.id,
            attempt_number=attempt_number,
            provider_name=str(getattr(provider, "provider_name", "unknown")),
            model_version=str(getattr(provider, "model_version", "unknown")),
            prompt_version=job.prompt_version or "unknown",
            status="running",
            request_summary=_request_summary(
                request, requested_count=job.requested_count, template=template
            ),
        )
        job.attempts.append(attempt)
        session.flush()
        started_at = utc_now()
        try:
            result = provider.generate(request)
        except ProviderFailure as exc:
            _finish_attempt(attempt, status="failed", failure_code=exc.code, started_at=started_at)
            job.failure_code = exc.code
            session.flush()
            if exc.retryable and attempt_number < max_attempts:
                continue
            break

        if job.cancel_requested_at is None:
            session.expire(job)
            session.refresh(job)
        attempt.provider_name = result.provider_name
        attempt.model_version = result.model_version
        attempt.response_summary = {"candidate_count": len(result.candidates)}
        if job.cancel_requested_at is not None:
            _finish_attempt(attempt, status="cancelled", failure_code=None, started_at=started_at)
            job.status = GenerationJobStatus.CANCELLED
            job.finished_at = utc_now()
            session.flush()
            return job
        _finish_attempt(attempt, status="succeeded", failure_code=None, started_at=started_at)
        job.status = GenerationJobStatus.VALIDATING
        generated = _persist_valid_candidates(
            session, job=job, attempt=attempt, candidates=result.candidates
        )
        job.succeeded_count += generated
        session.flush()
        break

    job.failed_count = max(job.requested_count - job.succeeded_count, 0)
    job.finished_at = utc_now()
    if job.cancel_requested_at is not None:
        job.status = GenerationJobStatus.CANCELLED
    elif job.succeeded_count == job.requested_count:
        job.status = GenerationJobStatus.READY_FOR_REVIEW
    elif job.succeeded_count:
        job.status = GenerationJobStatus.PARTIALLY_FAILED
    else:
        job.status = GenerationJobStatus.FAILED
    session.flush()
    return job


def cancel_generation_job(session: Session, *, job: GenerationJob) -> GenerationJob:
    if job.status in {GenerationJobStatus.READY_FOR_REVIEW, GenerationJobStatus.PARTIALLY_FAILED}:
        raise GenerationServiceError("a completed generation job cannot be cancelled")
    job.cancel_requested_at = utc_now()
    if job.status is GenerationJobStatus.QUEUED:
        job.status = GenerationJobStatus.CANCELLED
        job.finished_at = job.cancel_requested_at
    session.flush()
    return job


def _provider_request(
    session: Session, job: GenerationJob, *, teacher_constraint: str | None
) -> GenerationRequest:
    if teacher_constraint is not None:
        try:
            assert_deidentified_text(teacher_constraint)
        except ProcessorPolicyError as exc:
            raise GenerationServiceError("teacher_constraint_contains_pii") from exc
    question_types = job.distribution_json.get("question_types", [])
    if not isinstance(question_types, list) or not all(
        isinstance(item, str) for item in question_types
    ):
        raise GenerationServiceError("generation job question type distribution is invalid")
    revision = session.get(CurriculumObjectiveRevision, job.curriculum_objective_revision_id)
    if revision is None:
        raise GenerationServiceError("generation job objective revision was not found")
    return GenerationRequest(
        objective_revision_id=job.curriculum_objective_revision_id,
        objective_text=revision.text,
        knowledge_point=revision.objective.knowledge_point,
        difficulty_min=revision.difficulty_min,
        difficulty_max=revision.difficulty_max,
        grade=job.grade or "unspecified",
        subject=job.subject or "unspecified",
        question_types=question_types,
        requested_count=job.requested_count,
        policy_version=job.policy_version or "unknown",
        prompt_version=job.prompt_version or "unknown",
        teacher_constraint=teacher_constraint,
    )


def _persist_valid_candidates(
    session: Session,
    *,
    job: GenerationJob,
    attempt: GenerationAttempt,
    candidates: list[GeneratedCandidate],
) -> int:
    valid_count = 0
    allowed_question_types = set(job.distribution_json.get("question_types", []))
    for candidate in candidates:
        if valid_count + job.succeeded_count >= job.requested_count:
            break
        if candidate.objective_revision_id != job.curriculum_objective_revision_id:
            continue
        if candidate.question_type not in allowed_question_types:
            continue
        if validate_policy(candidate.question_type, candidate.policy_version, candidate.rule_json):
            continue
        content = candidate.model_dump(mode="json")
        draft = GeneratedQuestionDraft(
            job_id=job.id,
            generation_attempt_id=attempt.id,
            ordinal=job.succeeded_count + valid_count + 1,
            content_hash=_content_hash(content),
            candidate_json=content,
            teacher_state="pending_review",
        )
        job.drafts.append(draft)
        attempt.drafts.append(draft)
        session.flush()
        session.add(
            GeneratedQuestionDraftRevision(
                id=draft.current_revision_id,
                generated_question_draft_id=draft.id,
                revision_number=1,
                candidate_json=content,
                content_hash=draft.content_hash,
            )
        )
        valid_count += 1
    return valid_count


def _request_digest(request: GenerationJobRequest) -> str:
    content = request.model_dump(mode="json", exclude={"idempotency_key"})
    return _content_hash(content)


def _request_summary(
    request: GenerationRequest, *, requested_count: int, template: PromptTemplate
) -> dict[str, object]:
    return {
        "objective_revision_id": str(request.objective_revision_id),
        "grade": request.grade,
        "subject": request.subject,
        "question_types": request.question_types,
        "policy_version": request.policy_version,
        "prompt_version": request.prompt_version,
        "prompt_template": {
            "version": template.version,
            "schema_version": template.schema_version,
            "profile_scope": template.profile_scope,
            "allowed_question_types": sorted(template.allowed_question_types),
            "fingerprint": template.fingerprint,
        },
        "requested_count": requested_count,
    }


def _content_hash(content: object) -> str:
    serialized = json.dumps(content, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()


def _finish_attempt(
    attempt: GenerationAttempt,
    *,
    status: str,
    failure_code: str | None,
    started_at: datetime,
) -> None:
    finished_at = utc_now()
    attempt.status = status
    attempt.failure_code = failure_code
    attempt.finished_at = finished_at
    attempt.duration_ms = max(int((finished_at - started_at).total_seconds() * 1_000), 0)
