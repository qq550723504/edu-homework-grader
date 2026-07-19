from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import edu_grader_api.routers.questions as questions_router
import edu_grader_api.services.assignments as assignments_service
import edu_grader_api.services.reviews as reviews_service
from edu_grader_api.models import (
    AttemptAnswer,
    ClassTeacher,
    Classroom,
    Enrollment,
    GradingRun,
    ReviewTask,
    Role,
    Tenant,
    User,
)
from edu_grader_api.services.questions import GradeResult
from test_assignments import ISSUER, authorize
from test_assignments import client as _client_fixture
from test_assignments import session as _session_fixture


client = _client_fixture
session = _session_fixture


M2_RULE = {
    "expected": ["Add", "x", 1],
    "variables": ["x"],
    "required_form": "expanded",
    "max_score": 4,
}
M2_EVIDENCE = {
    "max_score": 4,
    "confidence": 1.0,
    "requires_review": True,
    "criteria": [
        {
            "code": "algebraic_equivalence",
            "passed": True,
            "score": 4,
            "max_score": 4,
        }
    ],
    "feedback": [{"type": "result", "message": "表达式等价。"}],
    "dependency_versions": {"grader": "e2e-m2@1"},
}
M2_CASES = (
    "correct",
    "incorrect",
    "empty",
    "boundary",
    "invalid_ast",
    "invalid_mathjson",
    "resource_limit",
)
M2_ANSWER = {
    "format": "mathjson-v1",
    "latex": "x+1",
    "mathjson": ["Add", "x", 1],
}


class DeterministicM2Client:
    def __init__(self, _: str) -> None:
        pass

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return {"kind": "symbol", "value": "x_plus_1"}

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        assert question_type == "M2"
        assert policy_version == "2"
        return GradeResult(
            decision="correct",
            score=4.0,
            grader_version="e2e-m2@1",
            evidence=M2_EVIDENCE,
        )


def seed_teacher_student_classroom(session: Session) -> tuple[User, User, Classroom]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    student = User(
        tenant=tenant,
        role=Role.STUDENT,
        school_id="S-001",
        oidc_issuer=ISSUER,
        oidc_subject="student",
        display_name="Student",
    )
    classroom = Classroom(tenant=tenant, code="7A", name="Year 7 A")
    session.add_all([tenant, teacher, student, classroom])
    session.flush()
    session.add_all(
        [
            ClassTeacher(class_id=classroom.id, teacher_id=teacher.id),
            Enrollment(class_id=classroom.id, student_id=student.id),
        ]
    )
    session.commit()
    return teacher, student, classroom


def install_deterministic_m2_grader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(questions_router, "HttpGraderClient", DeterministicM2Client)
    monkeypatch.setattr(assignments_service, "HttpGraderClient", DeterministicM2Client)
    monkeypatch.setattr(reviews_service, "HttpGraderClient", DeterministicM2Client)


def create_and_publish_assignment(
    client: TestClient, teacher: User, classroom: Classroom, version_id: str
) -> str:
    created = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json={
            "class_id": str(classroom.id),
            "title": "Expression equivalence",
            "subject": "mathematics",
            "due_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
            "submission_rule": {"allow_late": False},
        },
    )
    assert created.status_code == 201
    assignment_id = created.json()["id"]
    item = client.post(
        f"/v1/assignments/{assignment_id}/items",
        headers=authorize(client, teacher),
        json={"question_version_id": version_id, "position": 1},
    )
    assert item.status_code == 201
    published = client.post(
        f"/v1/assignments/{assignment_id}/publish", headers=authorize(client, teacher)
    )
    assert published.status_code == 200
    return assignment_id


def open_assignment(client: TestClient, student: User, assignment_id: str) -> tuple[str, str, dict[str, object]]:
    detail = client.get(
        f"/v1/student/assignments/{assignment_id}", headers=authorize(client, student)
    )
    assert detail.status_code == 200
    body = detail.json()
    return body["attempt"]["id"], body["items"][0]["id"], body


def save_mathjson_answer(
    client: TestClient, student: User, attempt_id: str, item_id: str
):
    return client.put(
        f"/v1/student/attempts/{attempt_id}/answers/{item_id}",
        headers=authorize(client, student),
        json={"answer": M2_ANSWER, "version": 0},
    )


def submit_once(client: TestClient, student: User, assignment_id: str):
    return client.post(
        f"/v1/student/assignments/{assignment_id}/submit",
        headers=authorize(client, student) | {"Idempotency-Key": str(uuid4())},
    )


def publish_after_teacher_confirmation(
    client: TestClient, session: Session, teacher: User, assignment_id: str, attempt_id: str
):
    tasks = client.get(
        f"/v1/review-tasks?assignment_id={assignment_id}", headers=authorize(client, teacher)
    )
    assert tasks.status_code == 200
    assert any(task["attempt_id"] == attempt_id for task in tasks.json()["review_tasks"])
    task = session.scalar(
        select(ReviewTask)
        .join(AttemptAnswer)
        .where(AttemptAnswer.attempt_id == UUID(attempt_id))
    )
    assert task is not None
    confirmed = client.post(
        f"/v1/review-tasks/{task.id}/decisions",
        headers=authorize(client, teacher),
        json={"action": "confirm", "version": task.version},
    )
    assert confirmed.status_code == 201
    return client.post(
        f"/v1/assignments/{assignment_id}/attempts/{attempt_id}/publish-results",
        headers=authorize(client, teacher),
    )


def correction_round_trip(
    client: TestClient,
    session: Session,
    teacher: User,
    student: User,
    assignment_id: str,
    attempt_id: str,
):
    appeal = client.post(
        f"/v1/student/attempts/{attempt_id}/appeals",
        headers=authorize(client, student),
        json={"reason": "Please review my equivalent expression."},
    )
    assert appeal.status_code == 201
    approved = client.post(
        f"/v1/review-appeals/{appeal.json()['id']}/decisions",
        headers=authorize(client, teacher),
        json={"approve": True, "version": 0},
    )
    assert approved.status_code == 201
    correction_attempt_id = approved.json()["correction_attempt_id"]

    detail = client.get(
        f"/v1/student/assignments/{assignment_id}", headers=authorize(client, student)
    )
    assert detail.status_code == 200
    item_id = detail.json()["items"][0]["id"]
    assert save_mathjson_answer(client, student, correction_attempt_id, item_id).status_code == 200
    submitted = client.post(
        f"/v1/student/attempts/{correction_attempt_id}/submit",
        headers=authorize(client, student) | {"Idempotency-Key": str(uuid4())},
    )
    assert submitted.status_code == 200
    return publish_after_teacher_confirmation(
        client, session, teacher, assignment_id, correction_attempt_id
    )


def test_teacher_to_student_correction_vertical_slice(client, session, monkeypatch) -> None:
    teacher, student, classroom = seed_teacher_student_classroom(session)
    install_deterministic_m2_grader(monkeypatch)

    draft = client.post(
        "/v1/questions",
        headers=authorize(client, teacher),
        json={
            "title": "Expand x plus one",
            "prompt": "Write x + 1 in expanded form.",
            "question_type": "M2",
            "policy_version": "2",
            "rule": M2_RULE,
        },
    )
    assert draft.status_code == 201
    version_id = draft.json()["id"]
    for category in M2_CASES:
        test_case = client.post(
            f"/v1/question-versions/{version_id}/test-cases",
            headers=authorize(client, teacher),
            json={
                "category": category,
                "answer": {"answer": M2_ANSWER},
                "expected_decision": "correct",
                "expected_score": 4.0,
                "expected_evidence": M2_EVIDENCE,
            },
        )
        assert test_case.status_code == 201
    assert (
        client.post(
            f"/v1/question-versions/{version_id}/test-runs", headers=authorize(client, teacher)
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/v1/question-versions/{version_id}/publish", headers=authorize(client, teacher)
        ).status_code
        == 200
    )

    assignment_id = create_and_publish_assignment(client, teacher, classroom, version_id)
    attempt_id, item_id, before_submission = open_assignment(client, student, assignment_id)
    assert "grading" not in before_submission
    assert "expected" not in before_submission["items"][0]
    assert "rule_snapshot" not in before_submission["items"][0]
    assert save_mathjson_answer(client, student, attempt_id, item_id).status_code == 200
    submitted = submit_once(client, student, assignment_id)
    assert submitted.status_code == 200

    run = session.scalar(
        select(GradingRun).where(GradingRun.question_version_id == UUID(version_id))
    )
    assert run is not None
    assert run.question_version_id == UUID(version_id)
    assert run.policy_version == "2"
    assert run.grader_version == "e2e-m2@1"
    assert run.evidence_json["criteria"] == M2_EVIDENCE["criteria"]

    assert (
        publish_after_teacher_confirmation(client, session, teacher, assignment_id, attempt_id).status_code
        == 201
    )
    published_detail = client.get(
        f"/v1/student/assignments/{assignment_id}", headers=authorize(client, student)
    )
    assert published_detail.status_code == 200
    assert published_detail.json()["grading"] == [
        {
            "assignment_item_id": item_id,
            "score": 4.0,
            "max_score": 4.0,
            "feedback": M2_EVIDENCE["feedback"],
        }
    ]
    assert "rule_snapshot" not in published_detail.json()
    assert "expected" not in published_detail.json()["items"][0]
    assert (
        correction_round_trip(client, session, teacher, student, assignment_id, attempt_id).status_code
        == 201
    )
    correction_detail = client.get(
        f"/v1/student/assignments/{assignment_id}", headers=authorize(client, student)
    )
    assert correction_detail.status_code == 200
    corrections = correction_detail.json()["corrections"]
    assert corrections[0]["attempt_id"] != attempt_id
    assert corrections[0]["status"] == "published"
