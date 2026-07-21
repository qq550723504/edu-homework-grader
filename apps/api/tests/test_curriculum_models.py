from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    CurriculumActivityType,
    CurriculumGradeMapping,
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


def grade_mapping(session: Session, profile: CurriculumProfile) -> CurriculumGradeMapping:
    mapping = CurriculumGradeMapping(
        profile=profile,
        internal_level="G1",
        external_label="一年级",
        position=1,
    )
    session.add(mapping)
    session.flush()
    return mapping


def test_objective_revision_number_is_unique_per_objective(session: Session) -> None:
    profile = active_profile(session)
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade_mapping(session, profile),
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([objective, revision(objective, 1), revision(objective, 1)])

    with pytest.raises(IntegrityError):
        session.commit()


def test_prerequisite_cannot_reference_the_same_revision(session: Session) -> None:
    profile = active_profile(session)
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade_mapping(session, profile),
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


def test_objective_belongs_to_one_profile_grade_mapping(session: Session) -> None:
    profile = active_profile(session)
    grade_mapping = CurriculumGradeMapping(
        profile=profile,
        internal_level="G1",
        external_label="一年级",
        position=1,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade_mapping,
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([grade_mapping, objective])
    session.commit()

    assert objective.grade_mapping_id == grade_mapping.id


def test_curriculum_foundation_is_the_alembic_head() -> None:
    config = Config("apps/api/alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "0013_curriculum_profile_foundation"
