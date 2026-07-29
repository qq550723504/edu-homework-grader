from __future__ import annotations

import logging
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import InvalidTokenError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_session
from ..github_oidc import GitHubOidcTrust, GitHubOidcVerifier, GitHubWorkflowIdentity
from ..models import OperationalEvaluationRun, OperationalEvaluationRunStatus, utc_now
from ..services.operational_evaluation_runs import (
    OperationalEvaluationRunConflict,
    complete_run,
    create_run,
    fail_run,
    reconcile_run_failure,
)
from ..settings import settings

router = APIRouter(prefix="/v1/internal/operational-evaluations", tags=["operations"])
github_security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


class OperationalEvaluationJobLauncher(Protocol):
    def launch(self, *, run_id: str, spec_json: dict[str, object], callback_token: str) -> None: ...

    def delete_callback_secret(self, *, run_id: str) -> None: ...

    def terminal_failure_code(self, *, run_id: str) -> str | None: ...


class StartOperationalEvaluationRequest(BaseModel):
    spec: dict[str, object]


class CompleteOperationalEvaluationRequest(BaseModel):
    report: dict[str, object] | None = None
    failure_code: str | None = None


def get_github_oidc_verifier() -> GitHubOidcVerifier:
    return GitHubOidcVerifier(GitHubOidcTrust.from_settings(settings))


def get_operational_evaluation_job_launcher() -> OperationalEvaluationJobLauncher:
    from ..services.operational_evaluation_kubernetes import (
        KubernetesOperationalEvaluationJobLauncher,
    )

    return KubernetesOperationalEvaluationJobLauncher.from_settings(settings)


def get_github_workflow_identity(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(github_security)],
    verifier: Annotated[GitHubOidcVerifier, Depends(get_github_oidc_verifier)],
) -> GitHubWorkflowIdentity:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid GitHub OIDC token"
        )
    try:
        return verifier.verify(credentials.credentials)
    except (InvalidTokenError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid GitHub OIDC token"
        ) from None


def _run_for_identity(
    session: Session, run_id: UUID, identity: GitHubWorkflowIdentity
) -> OperationalEvaluationRun:
    run = session.get(OperationalEvaluationRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="evaluation run not found"
        )
    if (
        run.repository_id != identity.repository_id
        or run.repository_owner_id != identity.owner_id
        or run.github_run_id != identity.run_id
        or run.workflow_ref != identity.workflow_ref
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="evaluation run is not authorized"
        )
    return run


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def start_operational_evaluation(
    request: StartOperationalEvaluationRequest,
    session: Annotated[Session, Depends(get_session)],
    identity: Annotated[GitHubWorkflowIdentity, Depends(get_github_workflow_identity)],
    launcher: Annotated[
        OperationalEvaluationJobLauncher, Depends(get_operational_evaluation_job_launcher)
    ],
) -> dict[str, str]:
    try:
        created = create_run(session, identity=identity, spec_json=request.spec, now=utc_now())
    except OperationalEvaluationRunConflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="GitHub workflow run already has another evaluation spec",
        ) from None
    if created.callback_token is not None:
        launcher.launch(
            run_id=str(created.run.id),
            spec_json=request.spec,
            callback_token=created.callback_token,
        )
        created.run.status = OperationalEvaluationRunStatus.RUNNING
    session.commit()
    return {"id": str(created.run.id), "status": created.run.status.value}


@router.get("/{run_id}")
def operational_evaluation_status(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    identity: Annotated[GitHubWorkflowIdentity, Depends(get_github_workflow_identity)],
    launcher: Annotated[
        OperationalEvaluationJobLauncher, Depends(get_operational_evaluation_job_launcher)
    ],
) -> dict[str, str]:
    run = _run_for_identity(session, run_id, identity)
    if run.status is OperationalEvaluationRunStatus.RUNNING:
        failure_code = launcher.terminal_failure_code(run_id=str(run.id))
        if failure_code is not None:
            run = reconcile_run_failure(
                session, run_id=run.id, failure_code=failure_code, now=utc_now()
            )
            session.commit()
            try:
                launcher.delete_callback_secret(run_id=str(run.id))
            except Exception:
                logger.warning(
                    "operational evaluation reconciled callback Secret cleanup failed",
                    exc_info=True,
                )
    return {"id": str(run.id), "status": run.status.value}


@router.get("/{run_id}/report")
def operational_evaluation_report(
    run_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    identity: Annotated[GitHubWorkflowIdentity, Depends(get_github_workflow_identity)],
) -> dict[str, object]:
    run = _run_for_identity(session, run_id, identity)
    if run.status is not OperationalEvaluationRunStatus.SUCCEEDED or run.report_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="evaluation report is not ready"
        )
    return run.report_json


@router.post("/{run_id}/completion", status_code=status.HTTP_204_NO_CONTENT)
def complete_operational_evaluation(
    run_id: UUID,
    request: CompleteOperationalEvaluationRequest,
    session: Annotated[Session, Depends(get_session)],
    callback_token: Annotated[str | None, Header(alias="X-Operational-Evaluation-Callback")],
    launcher: Annotated[
        OperationalEvaluationJobLauncher, Depends(get_operational_evaluation_job_launcher)
    ],
) -> Response:
    try:
        if request.report is not None and request.failure_code is None:
            complete_run(
                session,
                run_id=run_id,
                callback_token=callback_token or "",
                report_json=request.report,
                now=utc_now(),
            )
        elif request.report is None and request.failure_code is not None:
            fail_run(
                session,
                run_id=run_id,
                callback_token=callback_token or "",
                failure_code=request.failure_code,
                now=utc_now(),
            )
        else:
            raise ValueError("operational evaluation callback is invalid")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid evaluation callback"
        ) from None
    session.commit()
    try:
        launcher.delete_callback_secret(run_id=str(run_id))
    except Exception:
        logger.warning("operational evaluation callback Secret cleanup failed", exc_info=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
