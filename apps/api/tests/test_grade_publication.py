from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_grader_api.models import ReviewTask
from edu_grader_api.services.assignments import get_student_assignment, save_answer, submit_attempt
from test_assignments import authorize, published_assignment_for_student
from test_assignments import client as _assignment_client
from test_assignments import session as _assignment_session
from test_reviews import DeterministicGrader


@pytest.fixture
def database_session() -> Session:
    yield from _assignment_session.__wrapped__()


@pytest.fixture
def api_client(database_session: Session, monkeypatch: pytest.MonkeyPatch):
    yield from _assignment_client.__wrapped__(database_session, monkeypatch)


def test_student_sees_final_score_only_after_teacher_publishes(
    api_client, database_session: Session
) -> None:
    student, _, assignment, item, _ = published_assignment_for_student(database_session)
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
        answer_json={"value": "5"},
        expected_version=0,
    )
    submit_attempt(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
        idempotency_key=str(uuid4()),
        grader_client=DeterministicGrader(),
    )
    task = database_session.scalar(select(ReviewTask))
    assert task is not None
    database_session.commit()

    before = api_client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
    )
    confirmed = api_client.post(
        f"/v1/review-tasks/batch-confirm?assignment_id={assignment.id}",
        headers=authorize(api_client, assignment.created_by_user),
        json={"task_ids": [str(task.id)]},
    )
    published = api_client.post(
        f"/v1/assignments/{assignment.id}/attempts/{attempt.id}/publish-results",
        headers=authorize(api_client, assignment.created_by_user),
    )
    after = api_client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
    )

    assert before.status_code == 200
    assert "grading" not in before.json()
    assert confirmed.status_code == 201
    assert published.status_code == 201
    assert after.json()["grading"] == [
        {"assignment_item_id": str(item.id), "score": 1, "max_score": 1, "feedback": []}
    ]
