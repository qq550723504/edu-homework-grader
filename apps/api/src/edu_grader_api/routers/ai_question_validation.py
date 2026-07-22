from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_any_role
from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationJob,
    GenerationValidationRun,
    Role,
    User,
)
from ..services.grader import HttpGraderClient
from ..services.question_verification import run_candidate_verification
from ..settings import settings


router = APIRouter(prefix="/v1", tags=["AI question validation"])
_PUBLIC_FEATURE_SUMMARY_KEYS = frozenset(
    {
        "comparison_counts",
        "content_policy_version",
        "difficulty_signal",
        "embedding_dependency",
        "finding_count",
        "similarity_threshold",
    }
)
_PRIVATE_FEATURE_KEY_PARTS = ("digest", "fingerprint", "hash")


@router.post(
    "/ai-generated-questions/{draft_id}/validation-runs",
    status_code=status.HTTP_201_CREATED,
)
def create_validation_run_route(
    draft_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor = _actor(session, principal)
    draft = _tenant_draft(session, draft_id=draft_id, tenant_id=actor.tenant_id)
    revision = session.get(GeneratedQuestionDraftRevision, draft.current_revision_id)
    if revision is None or revision.generated_question_draft_id != draft.id:
        raise RuntimeError("current candidate revision is unavailable")
    run = run_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=HttpGraderClient(settings.grader_base_url),
    )
    append_audit_event(
        session,
        tenant_id=actor.tenant_id,
        actor_user_id=actor.id,
        event_type="ai_question_validation.completed",
        target_type="generated_question_draft",
        target_id=draft.id,
        metadata={
            "validation_run_id": str(run.id),
            "status": run.status.value,
            "finding_code_count": len(run.findings),
        },
    )
    session.commit()
    return _run_payload(run)


@router.get("/ai-generated-questions/{draft_id}/validation-runs")
def list_validation_runs_route(
    draft_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    actor = _actor(session, principal)
    draft = _tenant_draft(session, draft_id=draft_id, tenant_id=actor.tenant_id)
    runs = session.scalars(
        select(GenerationValidationRun)
        .where(GenerationValidationRun.generated_question_draft_id == draft.id)
        .order_by(GenerationValidationRun.run_number.desc())
        .limit(limit)
    ).all()
    return {"items": [_run_payload(run) for run in runs]}


@router.get("/ai-question-validation-runs/{run_id}")
def get_validation_run_route(
    run_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    actor = _actor(session, principal)
    run = session.scalar(
        select(GenerationValidationRun)
        .join(GenerationJob, GenerationValidationRun.generation_job_id == GenerationJob.id)
        .where(GenerationValidationRun.id == run_id, GenerationJob.tenant_id == actor.tenant_id)
    )
    if run is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "validation_run_not_found")
    return _run_payload(run)


def _actor(session: Session, principal: CurrentPrincipal) -> User:
    actor = session.get(User, UUID(principal.user_id))
    if actor is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "validation_actor_not_found")
    return actor


def _tenant_draft(session: Session, *, draft_id: UUID, tenant_id: UUID) -> GeneratedQuestionDraft:
    draft = session.scalar(
        select(GeneratedQuestionDraft)
        .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
        .where(GeneratedQuestionDraft.id == draft_id, GenerationJob.tenant_id == tenant_id)
    )
    if draft is None:
        raise _api_error(status.HTTP_404_NOT_FOUND, "generation_draft_not_found")
    return draft


def _run_payload(run: GenerationValidationRun) -> dict[str, object]:
    return {
        "id": str(run.id),
        "draft_id": str(run.generated_question_draft_id),
        "revision_number": run.draft_revision.revision_number,
        "run_number": run.run_number,
        "validator_version": run.validator_version,
        "ruleset_version": run.ruleset_version,
        "status": run.status.value,
        "feature_summary": _public_feature_summary(run.feature_summary_json),
        "created_at": run.created_at.isoformat(),
        "findings": [
            {
                "code": finding.code,
                "severity": finding.severity.value,
                "evidence": finding.evidence_json,
                "remediation": finding.remediation,
            }
            for finding in run.findings
        ],
    }


def _public_feature_summary(summary: dict[str, object]) -> dict[str, object]:
    return {
        key: _without_private_feature_keys(value)
        for key, value in summary.items()
        if key in _PUBLIC_FEATURE_SUMMARY_KEYS
    }


def _without_private_feature_keys(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_private_feature_keys(child)
            for key, child in value.items()
            if not any(part in str(key).casefold() for part in _PRIVATE_FEATURE_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_without_private_feature_keys(child) for child in value]
    return value


def _api_error(status_code: int, code: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code})
