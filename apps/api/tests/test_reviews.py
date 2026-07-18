from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from edu_grader_api.models import GradingPolicy
from edu_grader_api.services.assignments import get_student_assignment, save_answer, submit_attempt
from test_assignments import authorize, published_assignment_for_student
from test_assignments import client as _assignment_client
from test_assignments import session as _assignment_session
from test_english_grading_runs import FakeEnglishGraderClient


@pytest.fixture
def database_session() -> Session:
    yield from _assignment_session.__wrapped__()


@pytest.fixture
def api_client(database_session: Session, monkeypatch: pytest.MonkeyPatch):
    yield from _assignment_client.__wrapped__(database_session, monkeypatch)


def test_assigned_teacher_lists_manual_review_tasks(api_client, database_session: Session) -> None:
    student, _, assignment, item, version = published_assignment_for_student(database_session)
    version.question_type = "E4"
    version.grading_policy = GradingPolicy(question_type="E4", policy_version="2", json_schema={})
    version.rule_json = {"max_score": 1, "scoring_points": []}
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
        answer_json={"answer": "A concise answer."},
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
        "/v1/review-tasks", headers=authorize(api_client, assignment.created_by_user)
    )

    assert response.status_code == 200
    assert response.json()["review_tasks"] == [
        {
            "assignment_id": str(assignment.id),
            "attempt_id": str(attempt.id),
            "assignment_item_id": str(item.id),
            "reason": "needs_review",
            "question_type": "E4",
            "version": 0,
        }
    ]
