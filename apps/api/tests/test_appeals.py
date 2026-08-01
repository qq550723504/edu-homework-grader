from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    AppealStatus,
    AttemptStatus,
    CorrectionAttempt,
    GradePublication,
    ReviewAppeal,
    StudentAttempt,
)
from edu_grader_api.services.assignments import get_student_assignment, submit_attempt
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


def test_assigned_teacher_lists_actionable_appeals(api_client, database_session: Session) -> None:
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

    response = api_client.get(
        "/v1/review-appeals", headers=authorize(api_client, assignment.created_by_user)
    )

    assert response.status_code == 200
    assert response.json()["appeals"] == [
        {
            "id": str(appeal.id),
            "assignment_id": str(assignment.id),
            "assignment_title": "Published algebra",
            "attempt_id": str(attempt.id),
            "student_id": str(student.id),
            "student_name": student.display_name,
            "reason": "Please review.",
            "status": "open",
            "version": 0,
            "decision_reason": None,
        }
    ]


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


def test_correction_submission_targets_only_correction_attempt(database_session: Session) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Please review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all([correction, appeal])
    database_session.flush()
    database_session.add(
        CorrectionAttempt(
            original_attempt_id=original.id,
            correction_attempt_id=correction.id,
            appeal_id=appeal.id,
        )
    )

    submit_attempt(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
        attempt_id=correction.id,
        idempotency_key=str(__import__("uuid").uuid4()),
    )

    assert correction.status.value == "submitted"
    assert original.status.value == "draft"


def test_student_assignment_lists_published_correction_summary(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Please review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all([correction, appeal])
    database_session.flush()
    database_session.add_all(
        [
            CorrectionAttempt(
                original_attempt_id=original.id,
                correction_attempt_id=correction.id,
                appeal_id=appeal.id,
            ),
            GradePublication(
                attempt=correction, published_by_user_id=assignment.created_by_user_id
            ),
        ]
    )
    database_session.commit()

    response = api_client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
    )

    assert response.status_code == 200
    assert response.json()["corrections"] == [
        {"attempt_id": str(correction.id), "status": "published"}
    ]


def test_student_opens_approved_correction_attempt_for_editing(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Please review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all([correction, appeal])
    database_session.flush()
    database_session.add(
        CorrectionAttempt(
            original_attempt_id=original.id,
            correction_attempt_id=correction.id,
            appeal_id=appeal.id,
        )
    )
    database_session.commit()

    response = api_client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "correction_required"
    assert body["attempt"]["id"] == str(correction.id)
    assert body["attempt"]["attempt_number"] == 2
    assert body["corrections"] == [
        {"attempt_id": str(correction.id), "status": "correction_required"}
    ]


def test_approved_correction_can_be_saved_and_submitted_after_the_original_deadline(
    api_client, database_session: Session
) -> None:
    student, _, assignment, item, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Please review.",
        status=AppealStatus.APPROVED,
    )
    assignment.due_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assignment.submission_rule_json = {"allow_late": False}
    database_session.add_all([correction, appeal])
    database_session.flush()
    database_session.add(
        CorrectionAttempt(
            original_attempt_id=original.id,
            correction_attempt_id=correction.id,
            appeal_id=appeal.id,
        )
    )
    database_session.commit()

    saved = api_client.put(
        f"/v1/student/attempts/{correction.id}/answers/{item.id}",
        headers=authorize(api_client, student),
        json={"answer": {"format": "text-v1", "text": "5"}, "version": 0},
    )
    submitted = api_client.post(
        f"/v1/student/attempts/{correction.id}/submit",
        headers=authorize(api_client, student) | {"Idempotency-Key": str(uuid4())},
    )

    assert saved.status_code == 200
    assert submitted.status_code == 200


def test_nested_correction_uses_latest_unpublished_attempt_and_keeps_original_feedback(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    first_correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
        status=AttemptStatus.SUBMITTED,
    )
    first_appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="First review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all(
        [
            GradePublication(attempt=original, published_by_user_id=assignment.created_by_user_id),
            first_correction,
            first_appeal,
        ]
    )
    database_session.flush()
    next_correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=3,
    )
    second_appeal = ReviewAppeal(
        original_attempt_id=first_correction.id,
        student_id=student.id,
        reason="Second review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all([next_correction, second_appeal])
    database_session.flush()
    database_session.add_all(
        [
            CorrectionAttempt(
                original_attempt_id=original.id,
                correction_attempt_id=first_correction.id,
                appeal_id=first_appeal.id,
            ),
            GradePublication(
                attempt=first_correction, published_by_user_id=assignment.created_by_user_id
            ),
            CorrectionAttempt(
                original_attempt_id=first_correction.id,
                correction_attempt_id=next_correction.id,
                appeal_id=second_appeal.id,
            ),
        ]
    )
    database_session.commit()

    detail = api_client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(api_client, student)
    )
    listed = api_client.get("/v1/student/assignments", headers=authorize(api_client, student))

    assert detail.status_code == 200
    assert detail.json()["attempt"]["id"] == str(next_correction.id)
    assert detail.json()["grading"] is not None
    assert detail.json()["corrections"] == [
        {"attempt_id": str(first_correction.id), "status": "published"},
        {"attempt_id": str(next_correction.id), "status": "correction_required"},
    ]
    assert listed.json()["correction_required"][0]["status"] == "correction_required"


def test_approved_unfinished_correction_moves_original_assignment_to_correction_required(
    api_client, database_session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(database_session)
    _, original = get_student_assignment(
        database_session,
        tenant_id=student.tenant_id,
        student_id=student.id,
        assignment_id=assignment.id,
    )
    correction = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=2,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Please review.",
        status=AppealStatus.APPROVED,
    )
    database_session.add_all([correction, appeal])
    database_session.flush()
    database_session.add(
        CorrectionAttempt(
            original_attempt_id=original.id,
            correction_attempt_id=correction.id,
            appeal_id=appeal.id,
        )
    )
    database_session.commit()

    response = api_client.get("/v1/student/assignments", headers=authorize(api_client, student))

    assert response.status_code == 200
    assert response.json()["pending"] == []
    assert response.json()["correction_required"] == [
        {
            "id": str(assignment.id),
            "title": "Published algebra",
            "subject": "mathematics",
            "due_at": assignment.due_at.replace(tzinfo=timezone.utc).isoformat(),
            "status": "correction_required",
        }
    ]
