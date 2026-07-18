import pytest
from sqlalchemy.orm import Session

from edu_grader_api.models import AppealStatus, GradePublication, ReviewAppeal
from edu_grader_api.services.assignments import get_student_assignment
from test_assignments import authorize, published_assignment_for_student
from test_assignments import client as _assignment_client
from test_assignments import session as _assignment_session


@pytest.fixture
def database_session() -> Session:
    yield from _assignment_session.__wrapped__()


@pytest.fixture
def api_client(database_session: Session, monkeypatch: pytest.MonkeyPatch):
    yield from _assignment_client.__wrapped__(database_session, monkeypatch)


def test_student_creates_appeal_for_published_attempt(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    database_session.add(
        GradePublication(attempt=attempt, published_by_user_id=assignment.created_by_user_id)
    )
    database_session.commit()

    response = api_client.post(
        f"/v1/student/attempts/{attempt.id}/appeals",
        headers=authorize(api_client, student),
        json={"reason": "Please review the score."},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "open"


def test_assigned_teacher_approves_appeal_and_creates_correction_attempt(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    appeal = ReviewAppeal(
        original_attempt_id=attempt.id, student_id=student.id, reason="Please review."
    )
    database_session.add_all(
        [
            GradePublication(attempt=attempt, published_by_user_id=assignment.created_by_user_id),
            appeal,
        ]
    )
    database_session.commit()

    response = api_client.post(
        f"/v1/review-appeals/{appeal.id}/decisions",
        headers=authorize(api_client, assignment.created_by_user),
        json={"approve": True, "version": 0},
    )

    assert response.status_code == 201
    database_session.refresh(appeal)
    assert appeal.status is AppealStatus.APPROVED
    assert response.json()["correction_attempt_id"] != str(attempt.id)


def test_student_lists_own_appeal_status(api_client, database_session: Session) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    database_session.add(
        ReviewAppeal(original_attempt_id=attempt.id, student_id=student.id, reason="Please review.")
    )
    database_session.commit()

    response = api_client.get("/v1/student/appeals", headers=authorize(api_client, student))

    assert response.status_code == 200
    assert response.json()["appeals"][0]["attempt_id"] == str(attempt.id)
    assert response.json()["appeals"][0]["status"] == "open"


def test_teacher_rejection_requires_reason(api_client, database_session: Session) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, attempt = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    appeal = ReviewAppeal(
        original_attempt_id=attempt.id, student_id=student.id, reason="Please review."
    )
    database_session.add(appeal)
    database_session.commit()

    response = api_client.post(
        f"/v1/review-appeals/{appeal.id}/decisions",
        headers=authorize(api_client, assignment.created_by_user),
        json={"approve": False, "version": 0},
    )

    assert response.status_code == 422
