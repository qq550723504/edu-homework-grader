from copy import deepcopy

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    CurriculumImportStatus,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.curriculum_imports import (
    ImportDocument,
    StaleImportBaselineError,
    analyse_import,
    apply_import,
    parse_csv_document,
)


MINIMAL_DOCUMENT = {
    "profile": {
        "code": "example-math-2026",
        "name": "Example Mathematics",
        "jurisdiction": "example",
        "version_label": "2026",
    },
    "source": {
        "issuer": "Example Education Board",
        "title": "Example curriculum metadata",
        "canonical_url": "https://example.invalid/curriculum",
        "document_number": "EX-2026-01",
        "license": "CC BY 4.0",
        "curated_at": "2026-07-21",
    },
    "grade_mappings": [{"internal_level": "G1", "external_label": "Grade 1", "position": 1}],
    "objectives": [
        {
            "code": "EX-MATH-G1-NUM-001",
            "grade_level": "G1",
            "subject": "mathematics",
            "domain": "number",
            "text": "Represent small whole numbers with drawings and objects.",
            "source_locator": "section 1",
            "allowed_question_types": ["M1"],
            "difficulty_min": 0.0,
            "difficulty_max": 0.3,
            "activity_type": "scored_question",
            "change_summary": "Initial curated objective",
        }
    ],
    "prerequisites": [],
}


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def admin_user(session: Session) -> User:
    tenant = Tenant(slug="pilot", name="Pilot")
    user = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer="https://issuer.example.test",
        oidc_subject="curriculum-admin",
        display_name="Curriculum Admin",
        work_email="admin@example.test",
    )
    session.add(user)
    session.flush()
    return user


def test_json_and_csv_produce_the_same_normalized_document() -> None:
    document = ImportDocument.model_validate(MINIMAL_DOCUMENT)
    csv_document = parse_csv_document(
        "\n".join(
            [
                "code,grade_level,subject,domain,text,source_locator,allowed_question_types,difficulty_min,difficulty_max,activity_type,change_summary",
                "EX-MATH-G1-NUM-001,G1,mathematics,number,Represent small whole numbers with drawings and objects.,section 1,M1,0.0,0.3,scored_question,Initial curated objective",
            ]
        ),
        profile=document.profile,
        source=document.source,
        grade_mappings=document.grade_mappings,
    )

    assert csv_document.model_dump(mode="json") == document.model_dump(mode="json")


def test_analysis_reports_a_prerequisite_cycle_with_json_pointer(session: Session) -> None:
    document_data = deepcopy(MINIMAL_DOCUMENT)
    document_data["objectives"].append(
        {
            **document_data["objectives"][0],
            "code": "EX-MATH-G1-NUM-002",
            "text": "Compare two small whole numbers using objects.",
        }
    )
    document_data["prerequisites"] = [
        {
            "objective_code": "EX-MATH-G1-NUM-001",
            "prerequisite_code": "EX-MATH-G1-NUM-002",
        },
        {
            "objective_code": "EX-MATH-G1-NUM-002",
            "prerequisite_code": "EX-MATH-G1-NUM-001",
        },
    ]

    analysis = analyse_import(session, ImportDocument.model_validate(document_data))

    assert analysis.can_apply is False
    assert any(
        problem.code == "prerequisite_cycle" and problem.path == "/prerequisites/1"
        for problem in analysis.problems
    )


def test_analysis_reports_unknown_objective_grade_with_json_pointer(session: Session) -> None:
    document_data = deepcopy(MINIMAL_DOCUMENT)
    document_data["objectives"][0]["grade_level"] = "G2"

    analysis = analyse_import(session, ImportDocument.model_validate(document_data))

    assert analysis.can_apply is False
    assert any(
        problem.code == "unknown_grade" and problem.path == "/objectives/0/grade_level"
        for problem in analysis.problems
    )


def test_analysis_reports_question_type_that_does_not_match_the_subject(session: Session) -> None:
    document_data = deepcopy(MINIMAL_DOCUMENT)
    document_data["objectives"][0]["allowed_question_types"] = ["E1"]

    analysis = analyse_import(session, ImportDocument.model_validate(document_data))

    assert analysis.can_apply is False
    assert any(
        problem.code == "invalid_question_type"
        and problem.path == "/objectives/0/allowed_question_types/0"
        for problem in analysis.problems
    )


def test_apply_import_creates_a_draft_catalogue_candidate(session: Session) -> None:
    document = ImportDocument.model_validate(MINIMAL_DOCUMENT)
    analysis = analyse_import(session, document)

    batch = apply_import(session, document=document, analysis=analysis, actor=admin_user(session))

    assert batch.status is CurriculumImportStatus.DRAFT
    profile = session.scalar(
        select(CurriculumProfile).where(CurriculumProfile.code == document.profile.code)
    )
    assert profile is not None
    assert profile.status is CurriculumProfileStatus.DRAFT
    objective = session.scalar(
        select(CurriculumObjective).where(CurriculumObjective.profile_id == profile.id)
    )
    assert objective is not None
    assert objective.status is CurriculumProfileStatus.DRAFT
    revision = session.scalar(
        select(CurriculumObjectiveRevision).where(
            CurriculumObjectiveRevision.objective_id == objective.id
        )
    )
    assert revision is not None
    assert revision.status is CurriculumRevisionStatus.DRAFT
    assert revision.created_by_user_id == batch.submitted_by_user_id
    assert revision.import_batch_id == batch.id


def test_apply_import_is_idempotent_for_the_same_normalized_document(session: Session) -> None:
    document = ImportDocument.model_validate(MINIMAL_DOCUMENT)
    actor = admin_user(session)
    first = apply_import(
        session, document=document, analysis=analyse_import(session, document), actor=actor
    )

    second = apply_import(
        session, document=document, analysis=analyse_import(session, document), actor=actor
    )

    assert second.id == first.id
    assert len(session.scalars(select(CurriculumObjective)).all()) == 1


def test_changed_active_objective_creates_a_new_draft_revision(session: Session) -> None:
    actor = admin_user(session)
    initial_document = ImportDocument.model_validate(MINIMAL_DOCUMENT)
    apply_import(
        session,
        document=initial_document,
        analysis=analyse_import(session, initial_document),
        actor=actor,
    )
    profile = session.scalar(select(CurriculumProfile))
    objective = session.scalar(select(CurriculumObjective))
    active_revision = session.scalar(select(CurriculumObjectiveRevision))
    assert profile is not None and objective is not None and active_revision is not None
    profile.status = CurriculumProfileStatus.ACTIVE
    objective.status = CurriculumProfileStatus.ACTIVE
    active_revision.status = CurriculumRevisionStatus.ACTIVE
    session.flush()

    changed_data = deepcopy(MINIMAL_DOCUMENT)
    changed_data["objectives"][0]["text"] = "Compare small whole numbers with drawings and objects."
    changed_data["objectives"][0]["change_summary"] = "Clarify comparison objective"
    changed_document = ImportDocument.model_validate(changed_data)
    batch = apply_import(
        session,
        document=changed_document,
        analysis=analyse_import(session, changed_document),
        actor=actor,
    )

    revisions = session.scalars(
        select(CurriculumObjectiveRevision)
        .where(CurriculumObjectiveRevision.objective_id == objective.id)
        .order_by(CurriculumObjectiveRevision.revision_number)
    ).all()
    assert [revision.status for revision in revisions] == [
        CurriculumRevisionStatus.ACTIVE,
        CurriculumRevisionStatus.DRAFT,
    ]
    assert revisions[1].import_batch_id == batch.id
    assert revisions[1].revision_number == 2


def test_apply_import_rejects_a_dry_run_after_its_catalogue_baseline_changes(
    session: Session,
) -> None:
    document = ImportDocument.model_validate(MINIMAL_DOCUMENT)
    actor = admin_user(session)
    stale_analysis = analyse_import(session, document)
    apply_import(session, document=document, analysis=stale_analysis, actor=actor)

    with pytest.raises(StaleImportBaselineError):
        apply_import(session, document=document, analysis=stale_analysis, actor=actor)
