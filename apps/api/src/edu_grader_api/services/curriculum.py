from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumActivityType,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
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


def list_active_objective_revisions(session: Session) -> list[CurriculumObjectiveRevision]:
    return list(
        session.scalars(
            select(CurriculumObjectiveRevision)
            .join(CurriculumObjective)
            .where(
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
    if activity_type is not CurriculumActivityType.SCORED_QUESTION:
        raise CurriculumValidationError("non-K levels require scored_question activity type")


def text_value(question_types: list[str]) -> bool:
    return bool(question_types) and all(isinstance(item, str) and item for item in question_types)
