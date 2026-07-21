from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_any_role, require_role
from ..models import (
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    Role,
)
from ..services.curriculum import (
    CurriculumValidationError,
    activate_objective_revision,
    create_objective_revision,
    create_prerequisite,
)


router = APIRouter(prefix="/v1/curriculum-profiles", tags=["curriculum"])
admin_router = APIRouter(prefix="/v1/admin/curriculum", tags=["curriculum administration"])


class CreateObjectiveRevisionRequest(BaseModel):
    revision_number: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=2_000)
    source_locator: str = Field(min_length=1, max_length=500)
    allowed_question_types: list[str] = Field(min_length=1)
    difficulty_min: float = Field(ge=0, le=1)
    difficulty_max: float = Field(ge=0, le=1)
    activity_type: CurriculumActivityType


class CurriculumSourceRequest(BaseModel):
    issuer: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    canonical_url: str = Field(min_length=1, max_length=2_000)
    version_label: str = Field(min_length=1, max_length=100)
    editorial_note: str | None = Field(default=None, max_length=1_000)


class CreateProfileRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=200)
    jurisdiction: str = Field(min_length=1, max_length=100)
    version_label: str = Field(min_length=1, max_length=100)
    source: CurriculumSourceRequest


class CreateGradeMappingRequest(BaseModel):
    internal_level: str = Field(min_length=1, max_length=10)
    external_label: str = Field(min_length=1, max_length=200)
    position: int = Field(ge=0)
    note: str | None = Field(default=None, max_length=500)


class CreateObjectiveRequest(BaseModel):
    grade_mapping_id: UUID
    code: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=100)
    domain: str = Field(min_length=1, max_length=200)
    unit: str | None = Field(default=None, max_length=200)
    knowledge_point: str | None = Field(default=None, max_length=200)


class CurriculumStatusTransitionRequest(BaseModel):
    status: CurriculumProfileStatus


class CreatePrerequisiteRequest(BaseModel):
    prerequisite_revision_id: UUID


class CurriculumRevisionStatusTransitionRequest(BaseModel):
    status: CurriculumRevisionStatus


@router.get("")
def list_profiles_route(
    _: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, str]]]:
    profiles = session.scalars(
        select(CurriculumProfile)
        .where(CurriculumProfile.status == CurriculumProfileStatus.ACTIVE)
        .order_by(CurriculumProfile.code)
    )
    return {
        "items": [
            {
                "id": str(profile.id),
                "code": profile.code,
                "name": profile.name,
                "jurisdiction": profile.jurisdiction,
                "version_label": profile.version_label,
            }
            for profile in profiles
        ]
    }


@router.get("/{profile_code}/grade-mappings")
def list_grade_mappings_route(
    profile_code: str,
    _: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, object]]]:
    profile = _active_profile(session, profile_code)
    mappings = session.scalars(
        select(CurriculumGradeMapping)
        .where(CurriculumGradeMapping.profile_id == profile.id)
        .order_by(CurriculumGradeMapping.position, CurriculumGradeMapping.id)
    )
    return {
        "items": [
            {
                "id": str(mapping.id),
                "internal_level": mapping.internal_level,
                "external_label": mapping.external_label,
                "position": mapping.position,
                "note": mapping.note,
            }
            for mapping in mappings
        ]
    }


@router.get("/{profile_code}/objectives")
def list_objectives_route(
    profile_code: str,
    _: Annotated[CurrentPrincipal, Depends(require_any_role(Role.ADMIN, Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
    grade_level: str | None = None,
    subject: str | None = None,
    domain: str | None = None,
    knowledge_point: str | None = None,
    question_type: str | None = Query(default=None, max_length=30),
) -> dict[str, list[dict[str, object]]]:
    profile = _active_profile(session, profile_code)
    statement = (
        select(CurriculumObjective, CurriculumGradeMapping, CurriculumObjectiveRevision)
        .join(
            CurriculumGradeMapping,
            CurriculumObjective.grade_mapping_id == CurriculumGradeMapping.id,
        )
        .join(
            CurriculumObjectiveRevision,
            CurriculumObjectiveRevision.objective_id == CurriculumObjective.id,
        )
        .where(
            CurriculumObjective.profile_id == profile.id,
            CurriculumObjective.status == CurriculumProfileStatus.ACTIVE,
            CurriculumObjectiveRevision.status == CurriculumRevisionStatus.ACTIVE,
        )
    )
    if grade_level:
        statement = statement.where(CurriculumGradeMapping.internal_level == grade_level)
    if subject:
        statement = statement.where(CurriculumObjective.subject == subject)
    if domain:
        statement = statement.where(CurriculumObjective.domain == domain)
    if knowledge_point:
        statement = statement.where(CurriculumObjective.knowledge_point == knowledge_point)
    if question_type:
        statement = statement.where(
            CurriculumObjectiveRevision.allowed_question_types.contains([question_type])
        )

    rows = session.execute(
        statement.order_by(
            CurriculumGradeMapping.position,
            CurriculumObjective.subject,
            CurriculumObjective.domain,
            CurriculumObjective.code,
            CurriculumObjectiveRevision.revision_number,
        )
    )
    return {
        "items": [
            {
                "id": str(objective.id),
                "code": objective.code,
                "subject": objective.subject,
                "domain": objective.domain,
                "unit": objective.unit,
                "knowledge_point": objective.knowledge_point,
                "grade_mapping": {
                    "id": str(mapping.id),
                    "internal_level": mapping.internal_level,
                    "external_label": mapping.external_label,
                },
                "revision": _revision_payload(revision),
            }
            for objective, mapping, revision in rows
        ]
    }


@admin_router.post("/profiles", status_code=status.HTTP_201_CREATED)
def create_profile_route(
    body: CreateProfileRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    try:
        with session.begin():
            source = CurriculumSourceRecord(**body.source.model_dump())
            profile = CurriculumProfile(
                code=body.code,
                name=body.name,
                jurisdiction=body.jurisdiction,
                version_label=body.version_label,
                status=CurriculumProfileStatus.DRAFT,
                source_record=source,
            )
            session.add(profile)
            session.flush()
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="curriculum.profile_created",
                target_type="curriculum_profile",
                target_id=profile.id,
                metadata={"code": profile.code, "source_record_id": source.id},
            )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="profile code already exists"
        ) from error
    return _profile_payload(profile)


@admin_router.post("/profiles/{profile_id}/grade-mappings", status_code=status.HTTP_201_CREATED)
def create_grade_mapping_route(
    profile_id: UUID,
    body: CreateGradeMappingRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    with session.begin():
        profile = session.get(CurriculumProfile, profile_id)
        if profile is None or profile.status is CurriculumProfileStatus.RETIRED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        mapping = CurriculumGradeMapping(profile=profile, **body.model_dump())
        session.add(mapping)
        session.flush()
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="curriculum.grade_mapping_created",
            target_type="curriculum_grade_mapping",
            target_id=mapping.id,
            metadata={"profile_id": profile.id, "internal_level": mapping.internal_level},
        )
    return _grade_mapping_payload(mapping)


@admin_router.post("/profiles/{profile_id}/objectives", status_code=status.HTTP_201_CREATED)
def create_objective_route(
    profile_id: UUID,
    body: CreateObjectiveRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    with session.begin():
        profile = session.get(CurriculumProfile, profile_id)
        mapping = session.get(CurriculumGradeMapping, body.grade_mapping_id)
        if (
            profile is None
            or profile.status is CurriculumProfileStatus.RETIRED
            or mapping is None
            or mapping.profile_id != profile_id
        ):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        objective = CurriculumObjective(
            profile=profile,
            grade_mapping=mapping,
            code=body.code,
            subject=body.subject,
            domain=body.domain,
            unit=body.unit,
            knowledge_point=body.knowledge_point,
            status=CurriculumProfileStatus.DRAFT,
        )
        session.add(objective)
        session.flush()
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="curriculum.objective_created",
            target_type="curriculum_objective",
            target_id=objective.id,
            metadata={"profile_id": profile.id, "code": objective.code},
        )
    return _objective_payload(objective)


@admin_router.post("/profiles/{profile_id}/transitions")
def transition_profile_route(
    profile_id: UUID,
    body: CurriculumStatusTransitionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    with session.begin():
        profile = session.get(CurriculumProfile, profile_id)
        if profile is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        _transition_status(profile, body.status)
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="curriculum.profile_status_changed",
            target_type="curriculum_profile",
            target_id=profile.id,
            metadata={"status": profile.status.value},
        )
    return _profile_payload(profile)


@admin_router.post("/objectives/{objective_id}/transitions")
def transition_objective_route(
    objective_id: UUID,
    body: CurriculumStatusTransitionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    with session.begin():
        objective = session.get(CurriculumObjective, objective_id)
        if objective is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        _transition_status(objective, body.status)
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="curriculum.objective_status_changed",
            target_type="curriculum_objective",
            target_id=objective.id,
            metadata={"status": objective.status.value},
        )
    return _objective_payload(objective)


@admin_router.post("/objectives/{objective_id}/revisions", status_code=status.HTTP_201_CREATED)
def create_objective_revision_route(
    objective_id: UUID,
    body: CreateObjectiveRevisionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            objective = session.get(CurriculumObjective, objective_id)
            if objective is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
                )
            revision = create_objective_revision(
                session,
                objective=objective,
                revision_number=body.revision_number,
                text=body.text,
                source_locator=body.source_locator,
                allowed_question_types=body.allowed_question_types,
                difficulty_min=body.difficulty_min,
                difficulty_max=body.difficulty_max,
                activity_type=body.activity_type,
            )
            session.flush()
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="curriculum.objective_revision_created",
                target_type="curriculum_objective_revision",
                target_id=revision.id,
                metadata={
                    "objective_id": revision.objective_id,
                    "revision_number": revision.revision_number,
                },
            )
    except CurriculumValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return _revision_payload(revision)


@admin_router.post("/objective-revisions/{revision_id}/activate")
def activate_objective_revision_route(
    revision_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    try:
        session.rollback()
        with session.begin():
            revision = session.get(CurriculumObjectiveRevision, revision_id)
            if revision is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
                )
            activate_objective_revision(
                session,
                revision=revision,
                reviewer_user_id=UUID(principal.user_id),
            )
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="curriculum.objective_revision_activated",
                target_type="curriculum_objective_revision",
                target_id=revision.id,
                metadata={
                    "objective_id": revision.objective_id,
                    "revision_number": revision.revision_number,
                },
            )
    except CurriculumValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return _revision_payload(revision)


@admin_router.post("/objective-revisions/{revision_id}/transitions")
def transition_objective_revision_route(
    revision_id: UUID,
    body: CurriculumRevisionStatusTransitionRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    session.rollback()
    with session.begin():
        revision = session.get(CurriculumObjectiveRevision, revision_id)
        if revision is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
        _transition_revision_status(revision, body.status)
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="curriculum.objective_revision_status_changed",
            target_type="curriculum_objective_revision",
            target_id=revision.id,
            metadata={"status": revision.status.value},
        )
    return _revision_payload(revision)


@admin_router.post(
    "/objective-revisions/{revision_id}/prerequisites", status_code=status.HTTP_201_CREATED
)
def create_prerequisite_route(
    revision_id: UUID,
    body: CreatePrerequisiteRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.ADMIN))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    try:
        session.rollback()
        with session.begin():
            revision = session.get(CurriculumObjectiveRevision, revision_id)
            prerequisite_revision = session.get(
                CurriculumObjectiveRevision, body.prerequisite_revision_id
            )
            if revision is None or prerequisite_revision is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
                )
            prerequisite = create_prerequisite(
                session,
                objective_revision=revision,
                prerequisite_revision=prerequisite_revision,
            )
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="curriculum.prerequisite_created",
                target_type="curriculum_prerequisite",
                target_id=prerequisite.id,
                metadata={
                    "objective_revision_id": revision.id,
                    "prerequisite_revision_id": prerequisite_revision.id,
                    "relation_type": prerequisite.relation_type,
                },
            )
    except CurriculumValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error

    return {"id": str(prerequisite.id), "relation_type": prerequisite.relation_type}


def _active_profile(session: Session, profile_code: str) -> CurriculumProfile:
    profile = session.scalar(
        select(CurriculumProfile).where(
            CurriculumProfile.code == profile_code,
            CurriculumProfile.status == CurriculumProfileStatus.ACTIVE,
        )
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return profile


def _revision_payload(revision: CurriculumObjectiveRevision) -> dict[str, object]:
    return {
        "id": str(revision.id),
        "revision_number": revision.revision_number,
        "text": revision.text,
        "source_locator": revision.source_locator,
        "allowed_question_types": revision.allowed_question_types,
        "difficulty_min": revision.difficulty_min,
        "difficulty_max": revision.difficulty_max,
        "activity_type": revision.activity_type.value,
        "status": revision.status.value,
    }


def _profile_payload(profile: CurriculumProfile) -> dict[str, object]:
    return {
        "id": str(profile.id),
        "code": profile.code,
        "name": profile.name,
        "jurisdiction": profile.jurisdiction,
        "version_label": profile.version_label,
        "status": profile.status.value,
    }


def _grade_mapping_payload(mapping: CurriculumGradeMapping) -> dict[str, object]:
    return {
        "id": str(mapping.id),
        "internal_level": mapping.internal_level,
        "external_label": mapping.external_label,
        "position": mapping.position,
        "note": mapping.note,
    }


def _objective_payload(objective: CurriculumObjective) -> dict[str, object]:
    return {
        "id": str(objective.id),
        "code": objective.code,
        "subject": objective.subject,
        "domain": objective.domain,
        "unit": objective.unit,
        "knowledge_point": objective.knowledge_point,
        "status": objective.status.value,
    }


def _transition_status(
    resource: CurriculumProfile | CurriculumObjective, target: CurriculumProfileStatus
) -> None:
    transitions = {
        CurriculumProfileStatus.DRAFT: {
            CurriculumProfileStatus.IN_REVIEW,
            CurriculumProfileStatus.RETIRED,
        },
        CurriculumProfileStatus.IN_REVIEW: {
            CurriculumProfileStatus.ACTIVE,
            CurriculumProfileStatus.RETIRED,
        },
        CurriculumProfileStatus.ACTIVE: {CurriculumProfileStatus.RETIRED},
        CurriculumProfileStatus.RETIRED: set(),
    }
    if target not in transitions[resource.status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot transition {resource.status.value} to {target.value}",
        )
    resource.status = target


def _transition_revision_status(
    revision: CurriculumObjectiveRevision, target: CurriculumRevisionStatus
) -> None:
    transitions = {
        CurriculumRevisionStatus.DRAFT: {
            CurriculumRevisionStatus.IN_REVIEW,
            CurriculumRevisionStatus.RETIRED,
        },
        CurriculumRevisionStatus.IN_REVIEW: {CurriculumRevisionStatus.RETIRED},
        CurriculumRevisionStatus.ACTIVE: {CurriculumRevisionStatus.RETIRED},
        CurriculumRevisionStatus.RETIRED: set(),
    }
    if target not in transitions[revision.status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"cannot transition {revision.status.value} to {target.value}",
        )
    revision.status = target
