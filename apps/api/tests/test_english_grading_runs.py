from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_grader_api.models import AttemptAnswer, GradingPolicy, GradingRun, GradingSignal
from edu_grader_api.services.assignments import get_student_assignment, save_answer, submit_attempt
from edu_grader_api.services.questions import GradeResult
from test_assignments import published_assignment_for_student
from test_assignments import session as _assignment_session
from test_assignments import authorize, client as _assignment_client


@pytest.fixture
def database_session() -> Session:
    yield from _assignment_session.__wrapped__()


@pytest.fixture
def api_client(database_session: Session, monkeypatch: pytest.MonkeyPatch):
    yield from _assignment_client.__wrapped__(database_session, monkeypatch)


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


class FakeEnglishGraderClient:
    def __init__(self) -> None:
        self.calls = 0

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.calls += 1
        assert (question_type, policy_version, answer_json) == (
            "E4",
            "2",
            {"answer": "The road closure delayed them."},
        )
        return GradeResult(
            decision="needs_review",
            score=0,
            grader_version="grader-english-1",
            evidence={
                "max_score": 1,
                "confidence": 0.8,
                "criteria": [
                    {
                        "code": "cause",
                        "score": 0,
                        "max_score": 1,
                        "passed": False,
                        "evidence": "no scoring-point evidence matched",
                    }
                ],
                "feedback": [{"type": "grammar", "message": "Use an"}],
                "signals": [
                    {
                        "kind": "scoring_point",
                        "code": "cause",
                        "highest_similarity": 0.95,
                        "similarity_threshold": 0.78,
                    }
                ],
                "requires_review": True,
            },
        )


def test_submit_persists_e4_evidence_without_leaking_rubric(
    database_session: Session,
) -> None:
    student, _, assignment, item, version = published_assignment_for_student(database_session)
    policy = GradingPolicy(question_type="E4", policy_version="2", json_schema={})
    version.question_type = "E4"
    version.grading_policy = policy
    version.rule_json = {
        "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
        "similarity_threshold": 0.78,
        "max_score": 1,
    }
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    save_answer(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        attempt_id=attempt.id,
        assignment_item_id=item.id,
        answer_json={"answer": "The road closure delayed them."},
        expected_version=0,
    )
    grader = FakeEnglishGraderClient()

    _, response = submit_attempt(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
        idempotency_key=str(uuid4()),
        grader_client=grader,
    )

    assert grader.calls == 1
    assert response["grading"] == [
        {
            "assignment_item_id": str(item.id),
            "decision": "needs_review",
            "score": 0,
            "max_score": 1,
            "requires_review": True,
            "feedback": [{"type": "grammar", "message": "Use an"}],
        }
    ]
    assert "evidence_phrases" not in str(response)
    run = database_session.scalar(select(GradingRun))
    assert run is not None
    assert run.thresholds_json == {"similarity": 0.78}
    scoring_signal = next(signal for signal in run.signals if signal.kind == "scoring_point")
    assert scoring_signal.evidence_json["highest_similarity"] == 0.95


def test_assigned_teacher_can_read_full_grading_evidence(
    api_client,
    database_session: Session,
) -> None:
    student, _, assignment, item, version = published_assignment_for_student(database_session)
    policy = GradingPolicy(question_type="E4", policy_version="2", json_schema={})
    version.question_type = "E4"
    version.grading_policy = policy
    version.rule_json = {
        "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
        "similarity_threshold": 0.78,
        "max_score": 1,
    }
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    save_answer(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        attempt_id=attempt.id,
        assignment_item_id=item.id,
        answer_json={"answer": "The road closure delayed them."},
        expected_version=0,
    )
    submit_attempt(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
        idempotency_key=str(uuid4()),
        grader_client=FakeEnglishGraderClient(),
    )

    response = api_client.get(
        f"/v1/assignments/{assignment.id}/attempts/{attempt.id}/grading-runs",
        headers=authorize(api_client, assignment.created_by_user),
    )

    assert response.status_code == 200
    assert response.json()["grading_runs"][0]["rule_snapshot"]["scoring_points"][0][
        "evidence_phrases"
    ] == ["bridge closed"]
