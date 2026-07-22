from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.services.curriculum import (
    CurriculumValidationError,
    create_prerequisite,
    create_objective_revision,
    list_active_objective_revisions,
    retire_objective_revision,
)
from edu_grader_api.models import (
    Base,
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumImportBatch,
    CurriculumImportIssue,
    CurriculumImportStatus,
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


def test_grade_mapping_defaults_complexity_rules_to_empty_object(session: Session) -> None:
    mapping = grade_mapping(session, active_profile(session))

    assert mapping.complexity_rules_json == {}


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


def test_latest_alembic_revision_is_the_head() -> None:
    config = Config("apps/api/alembic.ini")
    script = ScriptDirectory.from_config(config)

    assert script.get_current_head() == "0021_protect_ai_review_evidence"


def test_import_batch_keeps_row_location_and_lifecycle(session: Session) -> None:
    batch = CurriculumImportBatch(
        profile=active_profile(session),
        input_format="json",
        content_digest="a" * 64,
        baseline_fingerprint="b" * 64,
        status=CurriculumImportStatus.DRAFT,
        submitted_by_user_id=uuid4(),
        change_summary="Initial curated import",
        summary_json={"additions": 1},
    )
    issue = CurriculumImportIssue(
        batch=batch,
        source_path="/objectives/0/grade_level",
        source_row=None,
        source_column=None,
        code="unknown_grade",
        category="validation",
        message="internal level is not supported by this profile",
    )
    session.add_all([batch, issue])
    session.commit()

    stored = session.get(CurriculumImportBatch, batch.id)
    assert stored is not None
    assert stored.status is CurriculumImportStatus.DRAFT
    assert stored.issues[0].code == "unknown_grade"


def test_k_grade_rejects_scored_question_types(session: Session) -> None:
    profile = active_profile(session)
    mapping = CurriculumGradeMapping(
        profile=profile,
        internal_level="K3_4",
        external_label="3–4 岁",
        position=1,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="K-NUMBER-001",
        subject="early_learning",
        domain="number_sense",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([mapping, objective])
    session.flush()

    with pytest.raises(CurriculumValidationError, match="K levels only allow learning_activity-v1"):
        create_objective_revision(
            session,
            objective=objective,
            revision_number=1,
            text="Count three objects.",
            source_locator="number sense",
            allowed_question_types=["M1"],
            difficulty_min=0,
            difficulty_max=0.2,
            activity_type=CurriculumActivityType.SCORED_QUESTION,
        )


def test_retired_revision_is_excluded_from_active_objective_selection(session: Session) -> None:
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
    session.commit()

    retire_objective_revision(session, item)
    assert item.id not in {revision.id for revision in list_active_objective_revisions(session)}


def test_retired_profile_is_excluded_from_active_objective_selection(session: Session) -> None:
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
    session.commit()

    profile.status = CurriculumProfileStatus.RETIRED
    session.commit()

    assert item.id not in {revision.id for revision in list_active_objective_revisions(session)}


def test_prerequisite_rejects_an_indirect_cycle(session: Session) -> None:
    profile = active_profile(session)
    mapping = grade_mapping(session, profile)
    first_objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    second_objective = CurriculumObjective(
        profile=profile,
        grade_mapping=mapping,
        code="MATH-G1-NUM-002",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    first_revision = revision(first_objective, 1)
    second_revision = revision(second_objective, 1)
    session.add_all([first_objective, second_objective, first_revision, second_revision])
    session.flush()

    create_prerequisite(
        session,
        objective_revision=first_revision,
        prerequisite_revision=second_revision,
    )
    with pytest.raises(CurriculumValidationError, match="prerequisite cycle"):
        create_prerequisite(
            session,
            objective_revision=second_revision,
            prerequisite_revision=first_revision,
        )


def test_only_one_active_revision_can_exist_per_objective(session: Session) -> None:
    profile = active_profile(session)
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade_mapping(session, profile),
        code="MATH-G1-NUM-001",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    session.add_all([objective, revision(objective, 1), revision(objective, 2)])

    with pytest.raises(IntegrityError):
        session.commit()


def test_question_type_filter_uses_postgresql_jsonb_containment() -> None:
    statement = select(CurriculumObjectiveRevision).where(
        CurriculumObjectiveRevision.allowed_question_types.contains(["M1"])
    )

    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert " @> " in compiled
