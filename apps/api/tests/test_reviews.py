from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    AuditLog,
    GradingPolicy,
    ReviewReason,
    ReviewAction,
    ReviewTask,
    ReviewTaskStatus,
)
from edu_grader_api.services.assignments import get_student_assignment, save_answer, submit_attempt
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.services.reviews import decide_review_task
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


def test_assigned_teacher_reads_full_review_evidence(api_client, database_session: Session) -> None:
    student, _, assignment, item, version = published_assignment_for_student(database_session)
    version.question_type = "E4"
    version.grading_policy = GradingPolicy(question_type="E4", policy_version="2", json_schema={})
    version.rule_json = {"max_score": 1, "scoring_points": [{"id": "cause", "score": 1}]}
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
    task = database_session.scalar(select(ReviewTask))
    assert task is not None

    response = api_client.get(
        f"/v1/review-tasks/{task.id}", headers=authorize(api_client, assignment.created_by_user)
    )

    assert response.status_code == 200
    assert response.json()["answer"] == {"answer": "The road closure delayed them."}
    assert response.json()["rule_snapshot"] == version.rule_json
    assert response.json()["grading"]["requires_review"] is True
    assert response.json()["signals"][0]["kind"] == "criterion"


def test_teacher_adjusts_score_with_reason_and_resolves_task(
    api_client, database_session: Session
) -> None:
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
    task = database_session.scalar(select(ReviewTask))
    assert task is not None
    database_session.commit()

    response = api_client.post(
        f"/v1/review-tasks/{task.id}/decisions",
        headers=authorize(api_client, assignment.created_by_user),
        json={"action": "adjust_score", "score": 1, "reason": "Equivalent answer.", "version": 0},
    )

    assert response.status_code == 201
    assert response.json()["final_score"] == 1
    database_session.refresh(task)
    assert task.status is ReviewTaskStatus.RESOLVED
    assert task.version == 1
    assert task.decisions[0].original_score == 0
    assert task.decisions[0].reason == "Equivalent answer."
    assert database_session.scalar(
        select(AuditLog).where(AuditLog.event_type == "review.decision_recorded")
    )

    duplicate = api_client.post(
        f"/v1/review-tasks/{task.id}/decisions",
        headers=authorize(api_client, assignment.created_by_user),
        json={"action": "confirm", "version": 0},
    )
    assert duplicate.status_code == 409


class DeterministicGrader:
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult(
            decision="accepted",
            score=1,
            grader_version="grader-test",
            evidence={"max_score": 1, "confidence": 1, "requires_review": False, "feedback": []},
        )


def test_teacher_batch_confirms_deterministic_tasks(api_client, database_session: Session) -> None:
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
    assert task.reason is ReviewReason.AUTO_CONFIRMATION
    database_session.commit()

    response = api_client.post(
        f"/v1/review-tasks/batch-confirm?assignment_id={assignment.id}",
        headers=authorize(api_client, assignment.created_by_user),
        json={"task_ids": [str(task.id)]},
    )

    assert response.status_code == 201
    database_session.refresh(task)
    assert task.status is ReviewTaskStatus.RESOLVED


def test_regrade_supersedes_task_and_creates_replacement_run(database_session: Session) -> None:
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
    task = database_session.scalar(select(ReviewTask))
    assert task is not None
    original_run_id = task.grading_run_id

    decide_review_task(
        database_session,
        tenant_id=student.tenant_id,
        teacher_id=assignment.created_by_user_id,
        task_id=task.id,
        action=ReviewAction.REQUEST_REGRADE,
        version=0,
        score=None,
        reason="Check the dependency result again.",
        grader_client=FakeEnglishGraderClient(),
    )

    database_session.refresh(task)
    replacement = database_session.scalar(select(ReviewTask).where(ReviewTask.id != task.id))
    assert task.status is ReviewTaskStatus.SUPERSEDED
    assert replacement is not None
    assert replacement.grading_run_id != original_run_id
    assert replacement.status is ReviewTaskStatus.OPEN
