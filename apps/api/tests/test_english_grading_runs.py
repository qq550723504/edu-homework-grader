import pytest
from sqlalchemy.orm import Session

from edu_grader_api.models import AttemptAnswer, GradingPolicy, GradingRun, GradingSignal
from edu_grader_api.services.assignments import get_student_assignment
from test_assignments import published_assignment_for_student
from test_assignments import session as _assignment_session


@pytest.fixture
def database_session() -> Session:
    yield from _assignment_session.__wrapped__()


def test_grading_run_retains_rule_and_answer_snapshots_after_later_edits(
    database_session: Session,
) -> None:
    student, _, assignment, item, version = published_assignment_for_student(database_session)
    policy = GradingPolicy(question_type="E4", policy_version="2", json_schema={})
    version.question_type = "E4"
    version.grading_policy = policy
    version.rule_json = {
        "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
        "max_score": 1,
    }
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    answer = AttemptAnswer(
        attempt=attempt,
        assignment_item=item,
        answer_json={"answer": "bridge closed"},
        version=1,
    )
    run = GradingRun(
        attempt_answer=answer,
        question_version_id=version.id,
        grading_policy=policy,
        policy_version="2",
        rule_snapshot_json=version.rule_json.copy(),
        answer_snapshot_json=answer.answer_json.copy(),
        decision="needs_review",
        score=0,
        max_score=1,
        confidence=0.8,
        requires_review=True,
        grader_version="grader-english-1",
        dependency_versions_json={
            "embedding": {
                "id": "sentence-transformers/all-MiniLM-L6-v2",
                "revision": "pinned",
                "digest": "sha256:abc",
            }
        },
        thresholds_json={"similarity": 0.78},
        evidence_json={},
    )
    run.signals.append(
        GradingSignal(
            ordinal=0,
            kind="scoring_point",
            code="cause",
            passed=False,
            score=0,
            max_score=1,
            evidence_json={"highest_similarity": 0.95},
        )
    )
    database_session.add(run)
    database_session.commit()

    answer.answer_json = {"answer": "changed later"}
    version.rule_json = {"changed": True}
    database_session.commit()

    stored = database_session.get(GradingRun, run.id)
    assert stored is not None
    assert stored.answer_snapshot_json == {"answer": "bridge closed"}
    assert stored.rule_snapshot_json["scoring_points"][0]["id"] == "cause"
    assert stored.signals[0].evidence_json == {"highest_similarity": 0.95}
