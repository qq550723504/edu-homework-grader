from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from .operational_evaluation_runs import purge_expired_runs


def purge_expired_evaluations(
    session: Session, *, now: datetime, delete_secret: Callable[[str], None]
) -> list[UUID]:
    run_ids = purge_expired_runs(session, now=now)
    for run_id in run_ids:
        delete_secret(f"operational-evaluation-callback-{run_id}")
    return run_ids
