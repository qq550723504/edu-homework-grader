from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    CurriculumActivityType,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumPrerequisite,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def active_profile(session: Session) -> CurriculumProfile:
    source = CurriculumSourceRecord(
        issuer="Ministry of Education",
        title="Curriculum standard",
        canonical_url="https://example.test/curriculum",
        version_label="2022",
    )
    profile = CurriculumProfile(
        code="cn-compulsory-2022",
        name="Compulsory education",
        jurisdiction="CN",
        version_label="2022",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
    )
    session.add(profile)
    session.flush()
    return profile


def revision(objective: CurriculumObjective, number: int) -> CurriculumObjectiveRevision:
    return CurriculumObjectiveRevision(
        objective=objective,
        revision_number=number,
        text="Use whole numbers in simple situations.",
        source_locator="section 1",
        allowed_question_types=["M1"],
        difficulty_min=0.0,
        difficulty_max=0.4,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
        reviewed_by_user_id=uuid4(),
    )


def test_objective_revision_number_is_unique_per_objective(session: Session) -> None:
    objective = CurriculumObjective(
        profile=active_profile(session),
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([objective, revision(objective, 1), revision(objective, 1)])

    with pytest.raises(IntegrityError):
        session.commit()


def test_prerequisite_cannot_reference_the_same_revision(session: Session) -> None:
    objective = CurriculumObjective(
        profile=active_profile(session),
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    item = revision(objective, 1)
    session.add_all([objective, item])
    session.flush()
    session.add(
        CurriculumPrerequisite(
            objective_revision_id=item.id,
            prerequisite_revision_id=item.id,
            relation_type="requires",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()
