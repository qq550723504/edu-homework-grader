from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..github_oidc import GitHubWorkflowIdentity
from ..models import OperationalEvaluationRun, OperationalEvaluationRunStatus


RETENTION = timedelta(days=30)
_FORBIDDEN_REPORT_KEYS = frozenset({"records", "candidate_json", "prompt"})


class OperationalEvaluationRunConflict(ValueError):
    pass


@dataclass(frozen=True)
class CreatedOperationalEvaluationRun:
    run: OperationalEvaluationRun
    callback_token: str | None


def _digest_json(value: dict[str, object]) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _contains_raw_evaluation_data(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key.casefold() in _FORBIDDEN_REPORT_KEYS or _contains_raw_evaluation_data(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_raw_evaluation_data(item) for item in value)
    return False


def create_run(
    session: Session,
    *,
    identity: GitHubWorkflowIdentity,
    spec_json: dict[str, object],
    now: datetime,
) -> CreatedOperationalEvaluationRun:
    spec_digest = _digest_json(spec_json)
    existing = session.scalar(
        select(OperationalEvaluationRun).where(
            OperationalEvaluationRun.github_run_id == identity.run_id
        )
    )
    if existing is not None:
        if existing.spec_digest != spec_digest:
            raise OperationalEvaluationRunConflict(
                "github run already has a different evaluation spec"
            )
        return CreatedOperationalEvaluationRun(run=existing, callback_token=None)

    callback_token = secrets.token_urlsafe(32)
    run = OperationalEvaluationRun(
        github_run_id=identity.run_id,
        repository_id=identity.repository_id,
        repository_owner_id=identity.owner_id,
        workflow_ref=identity.workflow_ref,
        spec_digest=spec_digest,
        callback_token_digest=sha256(callback_token.encode("utf-8")).hexdigest(),
        status=OperationalEvaluationRunStatus.QUEUED,
        created_at=now,
    )
    session.add(run)
    session.flush()
    return CreatedOperationalEvaluationRun(run=run, callback_token=callback_token)


def complete_run(
    session: Session,
    *,
    run_id: UUID,
    callback_token: str,
    report_json: dict[str, object],
    now: datetime,
) -> OperationalEvaluationRun:
    run = session.get(OperationalEvaluationRun, run_id)
    if run is None or run.callback_token_digest is None:
        raise ValueError("operational evaluation callback is invalid")
    supplied_digest = sha256(callback_token.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(run.callback_token_digest, supplied_digest):
        raise ValueError("operational evaluation callback is invalid")
    if _contains_raw_evaluation_data(report_json):
        raise ValueError("raw evaluation data must not be persisted")

    run.status = OperationalEvaluationRunStatus.SUCCEEDED
    run.report_json = report_json
    run.report_sha256 = _digest_json(report_json)
    run.callback_token_digest = None
    run.completed_at = now
    run.expires_at = now + RETENTION
    session.flush()
    return run


def purge_expired_runs(session: Session, *, now: datetime) -> list[UUID]:
    runs = list(
        session.scalars(
            select(OperationalEvaluationRun).where(OperationalEvaluationRun.expires_at <= now)
        )
    )
    run_ids = [run.id for run in runs]
    for run in runs:
        session.delete(run)
    session.flush()
    return run_ids
