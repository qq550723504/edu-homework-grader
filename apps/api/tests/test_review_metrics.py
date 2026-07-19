from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    GradingPolicy,
    ReviewAction,
    ReviewDecision,
    ReviewReason,
    ReviewTask,
    ReviewTaskStatus,
    User,
)
from edu_grader_api.services.assignments import get_student_assignment, save_answer, submit_attempt
from test_assignments import authorize, published_assignment_for_student
from test_english_grading_runs import FakeEnglishGraderClient


pytest_plugins = ("test_reviews",)


def _resolved_review_task(api_client, database_session: Session):
    student, classroom, assignment, item, version = published_assignment_for_student(database_session)
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

    decision = api_client.post(
        f"/v1/review-tasks/{task.id}/decisions",
        headers=authorize(api_client, assignment.created_by_user),
        json={
            "action": "adjust_score",
            "version": 0,
            "score": 1,
            "reason": "accepted alternate method",
        },
    )
    assert decision.status_code == 201
    task.created_at = datetime(2026, 7, 10, 9, tzinfo=timezone.utc)
    recorded = database_session.scalar(select(ReviewDecision))
    assert recorded is not None
    recorded.created_at = task.created_at + timedelta(minutes=10)
    database_session.commit()
    return assignment, classroom, task


def test_teacher_review_metrics_summarize_resolved_tasks(api_client, database_session: Session) -> None:
    assignment, classroom, task = _resolved_review_task(api_client, database_session)
    second_task = ReviewTask(
        attempt_answer=task.attempt_answer,
        grading_run=task.grading_run,
        reason=ReviewReason.RULE_PROBLEM,
        status=ReviewTaskStatus.RESOLVED,
        active_key=None,
        version=1,
        created_at=datetime(2026, 7, 10, 9, tzinfo=timezone.utc),
        resolved_at=datetime(2026, 7, 10, 9, 20, tzinfo=timezone.utc),
    )
    database_session.add(second_task)
    database_session.flush()
    database_session.add(
        ReviewDecision(
            review_task=second_task,
            actor_user_id=assignment.created_by_user.id,
            action=ReviewAction.CONFIRM,
            original_score=0,
            final_score=0,
            task_version=0,
            created_at=datetime(2026, 7, 10, 9, 20, tzinfo=timezone.utc),
        )
    )
    database_session.commit()

    response = api_client.get(
        "/v1/review-metrics",
        headers=authorize(api_client, assignment.created_by_user),
        params={"class_id": str(classroom.id), "assignment_id": str(assignment.id)},
    )

    assert response.status_code == 200
    assert response.json() == {
        "handled_tasks": 2,
        "average_duration_seconds": 900,
        "median_duration_seconds": 900,
        "score_adjustment_rate": 0.5,
        "task_reasons": [
            {"reason": "needs_review", "count": 1},
            {"reason": "rule_problem", "count": 1},
        ],
        "decision_reasons": [{"reason": "accepted alternate method", "count": 1}],
    }


def test_teacher_review_metrics_allow_an_empty_time_range(api_client, database_session: Session) -> None:
    assignment, _, _ = _resolved_review_task(api_client, database_session)

    response = api_client.get(
        "/v1/review-metrics",
        headers=authorize(api_client, assignment.created_by_user),
        params={"from": "2026-07-11T00:00:00+00:00"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "handled_tasks": 0,
        "average_duration_seconds": 0,
        "median_duration_seconds": 0,
        "score_adjustment_rate": 0,
        "task_reasons": [],
        "decision_reasons": [],
    }


def test_teacher_review_metrics_do_not_expose_another_teachers_classes(
    api_client, database_session: Session
) -> None:
    assignment, _, _ = _resolved_review_task(api_client, database_session)
    unassigned_teacher = database_session.scalar(
        select(User).where(User.oidc_subject == "unassigned")
    )
    assert unassigned_teacher is not None

    response = api_client.get(
        "/v1/review-metrics", headers=authorize(api_client, unassigned_teacher)
    )

    assert response.status_code == 200
    assert response.json()["handled_tasks"] == 0
    assert response.json()["task_reasons"] == []
    assert response.json()["decision_reasons"] == []
