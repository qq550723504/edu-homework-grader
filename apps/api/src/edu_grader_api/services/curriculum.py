from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumActivityType,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumPrerequisite,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    utc_now,
)
from ..policies import question_policy_catalog


class CurriculumValidationError(ValueError):
    """Raised when a curriculum revision cannot become part of the catalogue."""


def create_objective_revision(
    session: Session,
    *,
    objective: CurriculumObjective,
    revision_number: int,
    text: str,
    source_locator: str,
    allowed_question_types: list[str],
    difficulty_min: float,
    difficulty_max: float,
    activity_type: CurriculumActivityType,
) -> CurriculumObjectiveRevision:
    _validate_revision(
        objective,
        allowed_question_types,
        difficulty_min,
        difficulty_max,
        activity_type,
    )
    revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=revision_number,
        text=text,
        source_locator=source_locator,
        allowed_question_types=allowed_question_types,
        difficulty_min=difficulty_min,
        difficulty_max=difficulty_max,
        activity_type=activity_type,
        status=CurriculumRevisionStatus.DRAFT,
    )
    session.add(revision)
    return revision


def retire_objective_revision(session: Session, revision: CurriculumObjectiveRevision) -> None:
    revision.status = CurriculumRevisionStatus.RETIRED
    session.add(revision)
    session.flush()


def activate_objective_revision(
    session: Session,
    *,
    revision: CurriculumObjectiveRevision,
    reviewer_user_id: UUID,
) -> CurriculumObjectiveRevision:
    """Activate exactly one immutable revision for an objective."""
    if revision.status is not CurriculumRevisionStatus.IN_REVIEW:
        raise CurriculumValidationError("only in-review revisions can be activated")
    objective = session.scalar(
        select(CurriculumObjective)
        .where(CurriculumObjective.id == revision.objective_id)
        .with_for_update()
    )
    if objective is None:
        raise CurriculumValidationError("objective does not exist")
    if objective.profile.status is not CurriculumProfileStatus.ACTIVE:
        raise CurriculumValidationError("objective profile is not active")
    if objective.status is not CurriculumProfileStatus.ACTIVE:
        raise CurriculumValidationError("objective is not active")

    active_revisions = session.scalars(
        select(CurriculumObjectiveRevision).where(
            CurriculumObjectiveRevision.objective_id == objective.id,
            CurriculumObjectiveRevision.status == CurriculumRevisionStatus.ACTIVE,
            CurriculumObjectiveRevision.id != revision.id,
        )
    )
    for active_revision in active_revisions:
        active_revision.status = CurriculumRevisionStatus.RETIRED
    session.flush()

    revision.status = CurriculumRevisionStatus.ACTIVE
    revision.reviewed_by_user_id = reviewer_user_id
    revision.reviewed_at = utc_now()
    session.add(revision)
    session.flush()
    return revision


def create_prerequisite(
    session: Session,
    *,
    objective_revision: CurriculumObjectiveRevision,
    prerequisite_revision: CurriculumObjectiveRevision,
) -> CurriculumPrerequisite:
    """Add a requires edge after proving it cannot create a dependency cycle."""
    if objective_revision.id == prerequisite_revision.id:
        raise CurriculumValidationError("prerequisite cannot reference itself")
    if objective_revision.objective.profile_id != prerequisite_revision.objective.profile_id:
        raise CurriculumValidationError("prerequisites must belong to the same profile")
    session.scalar(
        select(CurriculumProfile)
        .where(CurriculumProfile.id == objective_revision.objective.profile_id)
        .with_for_update()
    )
    if _depends_on(session, start=prerequisite_revision.id, target=objective_revision.id):
        raise CurriculumValidationError("prerequisite cycle detected")
    prerequisite = CurriculumPrerequisite(
        objective_revision_id=objective_revision.id,
        prerequisite_revision_id=prerequisite_revision.id,
        relation_type="requires",
    )
    session.add(prerequisite)
    session.flush()
    return prerequisite


def list_active_objective_revisions(session: Session) -> list[CurriculumObjectiveRevision]:
    return list(
        session.scalars(
            select(CurriculumObjectiveRevision)
            .join(CurriculumObjective)
            .join(CurriculumProfile)
            .where(
                CurriculumProfile.status == CurriculumProfileStatus.ACTIVE,
                CurriculumObjective.status == CurriculumProfileStatus.ACTIVE,
                CurriculumObjectiveRevision.status == CurriculumRevisionStatus.ACTIVE,
            )
            .order_by(CurriculumObjective.code, CurriculumObjectiveRevision.revision_number)
        )
    )


def _validate_revision(
    objective: CurriculumObjective,
    allowed_question_types: list[str],
    difficulty_min: float,
    difficulty_max: float,
    activity_type: CurriculumActivityType,
) -> None:
    if not text_value(allowed_question_types):
        raise CurriculumValidationError("at least one question type is required")
    if not 0 <= difficulty_min <= difficulty_max <= 1:
        raise CurriculumValidationError("difficulty must be between 0 and 1")

    internal_level = objective.grade_mapping.internal_level
    if internal_level.startswith("K"):
        if activity_type is not CurriculumActivityType.LEARNING_ACTIVITY or set(
            allowed_question_types
        ) != {"learning_activity-v1"}:
            raise CurriculumValidationError("K levels only allow learning_activity-v1")
        return

    supported_types = {entry["question_type"] for entry in question_policy_catalog()}
    unsupported_types = set(allowed_question_types) - supported_types
    if unsupported_types:
        raise CurriculumValidationError(
            f"unsupported question types: {', '.join(sorted(unsupported_types))}"
        )
    allowed_for_subject = {
        "mathematics": {"M1", "M2"},
        "english": {"E1", "E2", "E3", "E4"},
    }.get(objective.subject)
    if allowed_for_subject is None or not set(allowed_question_types).issubset(allowed_for_subject):
        raise CurriculumValidationError("question types do not match objective subject")
    if activity_type is not CurriculumActivityType.SCORED_QUESTION:
        raise CurriculumValidationError("non-K levels require scored_question activity type")


def text_value(question_types: list[str]) -> bool:
    return bool(question_types) and all(isinstance(item, str) and item for item in question_types)


def validate_internal_level(profile: CurriculumProfile, internal_level: str) -> None:
    supported_by_profile = {
        "cn-preschool-3-6-2012": {"K3_4", "K4_5", "K5_6"},
        "cn-compulsory-2022": {f"G{grade}" for grade in range(1, 10)},
        "cn-high-school-2017-2020": {"G10", "G11", "G12"},
        "cefr-2020": {f"G{grade}" for grade in range(1, 14)},
    }
    valid_levels = {"K3_4", "K4_5", "K5_6"} | {f"G{grade}" for grade in range(1, 14)}
    allowed_levels = supported_by_profile.get(profile.code, valid_levels)
    if internal_level not in allowed_levels:
        raise CurriculumValidationError("internal level is not supported by this profile")


def _depends_on(session: Session, *, start: UUID, target: UUID) -> bool:
    pending = [start]
    visited = set()
    while pending:
        revision_id = pending.pop()
        if revision_id == target:
            return True
        if revision_id in visited:
            continue
        visited.add(revision_id)
        pending.extend(
            session.scalars(
                select(CurriculumPrerequisite.prerequisite_revision_id).where(
                    CurriculumPrerequisite.objective_revision_id == revision_id
                )
            )
        )
    return False
