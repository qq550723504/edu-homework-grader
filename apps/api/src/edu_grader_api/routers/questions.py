from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import Question, QuestionTestCase, QuestionVersion, Role, VersionStatus
from ..services.grader import HttpGraderClient
from ..services.questions import (
    PublishConflict,
    QuestionPolicyValidationError,
    QuestionVersionAccessError,
    QuestionVersionStateError,
    create_question,
    create_successor_draft,
    publish_question_version,
    run_question_tests,
    update_draft,
)
from ..settings import settings


router = APIRouter(prefix="/v1/questions", tags=["questions"])
version_router = APIRouter(prefix="/v1/question-versions", tags=["questions"])


class CreateQuestionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=10_000)
    question_type: str = Field(min_length=1, max_length=20)
    policy_version: str = Field(min_length=1, max_length=20)
    rule: dict[str, object]


class UpdateQuestionVersionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=10_000)
    rule: dict[str, object] | None = None


class CreateTestCaseRequest(BaseModel):
    category: str = Field(min_length=1, max_length=30)
    answer: dict[str, object]
    expected_decision: str = Field(min_length=1, max_length=30)
    expected_score: float = Field(ge=0)
    expected_evidence: dict[str, object]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_question_route(
    body: CreateQuestionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | int]:
    session.rollback()
    try:
        with session.begin():
            version = create_question(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                title=body.title,
                prompt=body.prompt,
                question_type=body.question_type,
                policy_version=body.policy_version,
                rule_json=body.rule,
            )
            session.flush()
    except QuestionPolicyValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"errors": error.errors},
        ) from error

    return {
        "id": str(version.id),
        "title": body.title,
        "version_number": version.version_number,
        "status": version.status.value,
    }


@router.post("/{question_id}/versions", status_code=status.HTTP_201_CREATED)
def create_successor_version_route(
    question_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | int]:
    try:
        session.rollback()
        with session.begin():
            published_version = session.scalar(
                select(QuestionVersion)
                .join(Question)
                .where(
                    QuestionVersion.question_id == question_id,
                    Question.tenant_id == UUID(principal.tenant_id),
                    QuestionVersion.status == VersionStatus.PUBLISHED,
                )
                .order_by(QuestionVersion.version_number.desc())
                .limit(1)
            )
            if published_version is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
                )
            successor = create_successor_draft(
                session, published_version, actor_user_id=UUID(principal.user_id)
            )
            session.flush()
    except QuestionVersionAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None

    return {"id": str(successor.id), "version_number": successor.version_number, "status": "draft"}


@version_router.put("/{version_id}")
def update_question_version_route(
    version_id: UUID,
    body: UpdateQuestionVersionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            version = _tenant_version(session, version_id, UUID(principal.tenant_id))
            update_draft(
                session,
                version,
                actor_user_id=UUID(principal.user_id),
                prompt=body.prompt,
                rule_json=body.rule,
            )
    except QuestionVersionAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except QuestionPolicyValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"errors": error.errors},
        ) from error
    except QuestionVersionStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"id": str(version.id), "status": version.status.value}


@version_router.post("/{version_id}/test-cases", status_code=status.HTTP_201_CREATED)
def create_test_case_route(
    version_id: UUID,
    body: CreateTestCaseRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            version = _tenant_version(session, version_id, UUID(principal.tenant_id))
            update_draft(
                session, version, actor_user_id=UUID(principal.user_id), prompt=version.prompt
            )
            test_case = QuestionTestCase(
                question_version_id=version.id,
                category=body.category,
                answer_json=body.answer,
                expected_decision=body.expected_decision,
                expected_score=body.expected_score,
                expected_evidence_json=body.expected_evidence,
            )
            session.add(test_case)
            session.flush()
    except QuestionVersionAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except QuestionVersionStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"id": str(test_case.id), "category": test_case.category}


@version_router.post("/{version_id}/test-runs", status_code=status.HTTP_201_CREATED)
def run_test_cases_route(
    version_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            version = _tenant_version(session, version_id, UUID(principal.tenant_id))
            update_draft(
                session, version, actor_user_id=UUID(principal.user_id), prompt=version.prompt
            )
            run = run_question_tests(
                session,
                version,
                trigger="manual",
                grader_client=HttpGraderClient(settings.grader_base_url),
            )
    except QuestionVersionAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except QuestionVersionStateError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"id": str(run.id), "status": run.status.value}


@version_router.post("/{version_id}/publish")
def publish_question_version_route(
    version_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            version = _tenant_version(session, version_id, UUID(principal.tenant_id))
            published = publish_question_version(
                session, version, actor_user_id=UUID(principal.user_id)
            )
    except QuestionVersionAccessError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
        ) from None
    except PublishConflict as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return {"id": str(published.id), "status": published.status.value}


def _tenant_version(session: Session, version_id: UUID, tenant_id: UUID) -> QuestionVersion:
    version = session.scalar(
        select(QuestionVersion)
        .join(Question)
        .where(QuestionVersion.id == version_id, Question.tenant_id == tenant_id)
    )
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return version
