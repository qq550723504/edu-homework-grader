from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OperationalEvaluationRun, OperationalEvaluationRunStatus
from .operational_evaluation_runs import purge_expired_runs, reconcile_run_failure


def purge_expired_evaluations(
    session: Session, *, now: datetime, delete_secret: Callable[[str], None]
) -> list[UUID]:
    run_ids = purge_expired_runs(session, now=now)
    for run_id in run_ids:
        delete_secret(f"operational-evaluation-callback-{run_id}")
    return run_ids


def reconcile_terminal_evaluations(
    session: Session,
    *,
    now: datetime,
    terminal_failure_code: Callable[[UUID], str | None],
) -> list[UUID]:
    runs = list(
        session.scalars(
            select(OperationalEvaluationRun).where(
                OperationalEvaluationRun.status == OperationalEvaluationRunStatus.RUNNING
            )
        )
    )
    reconciled: list[UUID] = []
    for run in runs:
        failure_code = terminal_failure_code(run.id)
        if failure_code is not None:
            reconcile_run_failure(session, run_id=run.id, failure_code=failure_code, now=now)
            reconciled.append(run.id)
    return reconciled
