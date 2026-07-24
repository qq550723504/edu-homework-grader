from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
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
from edu_grader_api.services.objective_prerequisites import (
    OBJECTIVE_PREREQUISITE_RULESET_VERSION,
    evaluate_objective_prerequisite_alignment,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@dataclass(frozen=True)
class CurriculumGraph:
    target: CurriculumObjectiveRevision
    prerequisite: CurriculumObjectiveRevision
    outside: CurriculumObjectiveRevision


def curriculum_graph(
    session: Session, *, target_knowledge_point: str | None = "multiplication"
) -> CurriculumGraph:
    source = CurriculumSourceRecord(
        issuer="Example Board",
        title="Mathematics curriculum",
        canonical_url=f"https://curriculum.example.test/{uuid4()}",
        version_label="2026",
    )
    profile = CurriculumProfile(
        code=f"pilot-{uuid4()}",
        name="Pilot Mathematics",
        jurisdiction="pilot",
        version_label="2026",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
    )
    grade = CurriculumGradeMapping(
        profile=profile,
        internal_level="G5",
        external_label="Grade 5",
        position=5,
    )
    target_objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code="MATH-G5-MULTIPLICATION",
        subject="mathematics",
        domain="number",
        knowledge_point=target_knowledge_point,
        status=CurriculumProfileStatus.ACTIVE,
    )
    prerequisite_objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code="MATH-G4-ADDITION",
        subject="mathematics",
        domain="number",
        knowledge_point="whole-number addition",
        status=CurriculumProfileStatus.ACTIVE,
    )
    outside_objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code="MATH-G6-FRACTION-DIVISION",
        subject="mathematics",
        domain="number",
        knowledge_point="fraction division",
        status=CurriculumProfileStatus.ACTIVE,
    )

    def revision(objective: CurriculumObjective, number: int) -> CurriculumObjectiveRevision:
        return CurriculumObjectiveRevision(
            objective=objective,
            revision_number=number,
            text=f"Objective {number}",
            source_locator=f"section {number}",
            allowed_question_types=["M1"],
            difficulty_min=0,
            difficulty_max=1,
            activity_type=CurriculumActivityType.SCORED_QUESTION,
            status=CurriculumRevisionStatus.ACTIVE,
        )

    target = revision(target_objective, 1)
    prerequisite = revision(prerequisite_objective, 1)
    outside = revision(outside_objective, 1)
    session.add_all([target, prerequisite, outside])
    session.flush()
    session.add(
        CurriculumPrerequisite(
            objective_revision_id=target.id,
            prerequisite_revision_id=prerequisite.id,
            relation_type="requires",
        )
    )
    session.flush()
    return CurriculumGraph(target=target, prerequisite=prerequisite, outside=outside)


def test_target_and_transitive_prerequisite_aliases_are_allowed(session: Session) -> None:
    graph = curriculum_graph(session)

    target = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=graph.target,
        candidate_knowledge_point="  MULTIPLICATION  ",
    )
    prerequisite = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=graph.target,
        candidate_knowledge_point="whole-number addition",
    )

    assert target.resolution == "target"
    assert target.prerequisite_depth == 0
    assert target.findings == ()
    assert prerequisite.resolution == "prerequisite"
    assert prerequisite.prerequisite_depth == 1
    assert prerequisite.findings == ()
    assert prerequisite.feature_summary()["version"] == OBJECTIVE_PREREQUISITE_RULESET_VERSION


def test_known_objective_outside_prerequisite_closure_is_blocked_without_raw_text(
    session: Session,
) -> None:
    graph = curriculum_graph(session)

    evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=graph.target,
        candidate_knowledge_point="fraction division",
    )

    assert evaluation.resolution == "out_of_scope"
    assert evaluation.matched_objective_code == "MATH-G6-FRACTION-DIVISION"
    assert [finding.code for finding in evaluation.findings] == [
        "objective_prerequisite_out_of_scope"
    ]
    assert evaluation.findings[0].severity == "blocked"
    persisted = json.dumps(
        {
            "signal": evaluation.feature_summary(),
            "findings": [finding.evidence for finding in evaluation.findings],
        }
    )
    assert "fraction division" not in persisted
    assert "sha256:" in persisted


def test_unresolved_alias_warns_only_when_target_mapping_is_configured(session: Session) -> None:
    configured = curriculum_graph(session)
    configured_evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=configured.target,
        candidate_knowledge_point="unmapped advanced concept",
    )

    assert configured_evaluation.resolution == "unresolved"
    assert [finding.code for finding in configured_evaluation.findings] == [
        "objective_prerequisite_unresolved"
    ]
    assert configured_evaluation.findings[0].severity == "warning"

    legacy = curriculum_graph(session, target_knowledge_point=None)
    legacy_evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=legacy.target,
        candidate_knowledge_point="legacy free-form label",
    )

    assert legacy_evaluation.resolution == "unresolved"
    assert legacy_evaluation.findings == ()


def test_ambiguous_alias_produces_stable_warning(session: Session) -> None:
    graph = curriculum_graph(session)
    duplicate_objective = CurriculumObjective(
        profile=graph.target.objective.profile,
        grade_mapping=graph.target.objective.grade_mapping,
        code="MATH-G5-MULTIPLICATION-ALT",
        subject="mathematics",
        domain="number",
        knowledge_point="multiplication",
        status=CurriculumProfileStatus.ACTIVE,
    )
    duplicate_revision = CurriculumObjectiveRevision(
        objective=duplicate_objective,
        revision_number=1,
        text="Alternate multiplication objective",
        source_locator="section alternate",
        allowed_question_types=["M1"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add(duplicate_revision)
    session.flush()

    evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=graph.target,
        candidate_knowledge_point="multiplication",
    )

    assert evaluation.resolution == "ambiguous"
    assert [finding.code for finding in evaluation.findings] == ["objective_prerequisite_ambiguous"]
    assert evaluation.findings[0].evidence["match_count"] == 2


def test_cycle_in_reachable_graph_fails_closed(session: Session) -> None:
    graph = curriculum_graph(session)
    session.add(
        CurriculumPrerequisite(
            objective_revision_id=graph.prerequisite.id,
            prerequisite_revision_id=graph.target.id,
            relation_type="requires",
        )
    )
    session.flush()

    evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=graph.target,
        candidate_knowledge_point="multiplication",
    )

    assert evaluation.resolution == "graph_invalid"
    assert [finding.code for finding in evaluation.findings] == [
        "objective_prerequisite_graph_invalid"
    ]
    assert evaluation.findings[0].severity == "blocked"
    assert evaluation.findings[0].evidence["reason"] == "cycle_detected"
