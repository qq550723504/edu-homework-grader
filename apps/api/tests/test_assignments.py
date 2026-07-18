from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import (
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    ClassTeacher,
    Classroom,
    Enrollment,
    Question,
    QuestionVersion,
    Role,
    StudentAttempt,
    SubmissionReceipt,
    Tenant,
    User,
    VersionStatus,
)
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identity


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def authorize(client: TestClient, user: User) -> dict[str, str]:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject=user.oidc_subject or "", school_id=user.school_id)
    )
    return {"Authorization": "Bearer test-token"}


def make_classroom_data(
    session: Session,
) -> tuple[User, User, User, Classroom, QuestionVersion, QuestionVersion]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    unassigned_teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="unassigned",
        display_name="Unassigned",
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
    question = Question(tenant=tenant, created_by_user=teacher, title="Addition")
    published = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt="What is 2 + 3?",
        question_type="M1",
        grading_policy_id=uuid4(),
        rule_json={"expected": 5},
        created_by_user=teacher,
    )
    draft = QuestionVersion(
        question=question,
        version_number=2,
        status=VersionStatus.DRAFT,
        prompt="What is 3 + 3?",
        question_type="M1",
        grading_policy_id=uuid4(),
        rule_json={"expected": 6},
        created_by_user=teacher,
    )
    session.add_all(
        [tenant, teacher, unassigned_teacher, student, classroom, question, published, draft]
    )
    session.flush()
    session.add_all(
        [
            ClassTeacher(class_id=classroom.id, teacher_id=teacher.id),
            Enrollment(class_id=classroom.id, student_id=student.id),
        ]
    )
    session.commit()
    return teacher, unassigned_teacher, student, classroom, published, draft


def assignment_payload(classroom: Classroom) -> dict[str, object]:
    return {
        "class_id": str(classroom.id),
        "title": "Algebra",
        "subject": "mathematics",
        "due_at": datetime(2026, 7, 20, tzinfo=timezone.utc).isoformat(),
        "submission_rule": {"allow_late": False},
    }


def test_assigned_teacher_can_publish_a_versioned_assignment(
    client: TestClient, session: Session
) -> None:
    teacher, _, _, classroom, published, _ = make_classroom_data(session)

    created = client.post(
        "/v1/assignments", headers=authorize(client, teacher), json=assignment_payload(classroom)
    )

    assert created.status_code == 201
    assignment_id = created.json()["id"]
    item = client.post(
        f"/v1/assignments/{assignment_id}/items",
        headers=authorize(client, teacher),
        json={"question_version_id": str(published.id), "position": 1},
    )
    assert item.status_code == 201
    published_response = client.post(
        f"/v1/assignments/{assignment_id}/publish", headers=authorize(client, teacher)
    )

    assert published_response.status_code == 200
    assert published_response.json()["status"] == AssignmentStatus.PUBLISHED.value


def test_unassigned_teacher_and_draft_question_are_rejected(
    client: TestClient, session: Session
) -> None:
    teacher, unassigned_teacher, _, classroom, _, draft = make_classroom_data(session)

    forbidden = client.post(
        "/v1/assignments",
        headers=authorize(client, unassigned_teacher),
        json=assignment_payload(classroom),
    )
    assert forbidden.status_code == 404

    assignment = Assignment(
        tenant=classroom.tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Draft assignment",
        subject="mathematics",
        due_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        submission_rule_json={},
    )
    session.add(assignment)
    session.commit()

    draft_item = client.post(
        f"/v1/assignments/{assignment.id}/items",
        headers=authorize(client, teacher),
        json={"question_version_id": str(draft.id), "position": 1},
    )

    assert draft_item.status_code == 422


def published_assignment_for_student(
    session: Session,
) -> tuple[User, Classroom, Assignment, AssignmentItem, QuestionVersion]:
    teacher, _, student, classroom, published, _ = make_classroom_data(session)
    assignment = Assignment(
        tenant=classroom.tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Published algebra",
        subject="mathematics",
        due_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        submission_rule_json={"allow_late": False},
        status=AssignmentStatus.PUBLISHED,
        published_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    item = AssignmentItem(assignment=assignment, question_version=published, position=1)
    session.add_all([assignment, item])
    session.commit()
    return student, classroom, assignment, item, published


def test_enrolled_student_lists_pending_and_opens_frozen_assignment(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, _, published = published_assignment_for_student(session)

    listed = client.get("/v1/student/assignments", headers=authorize(client, student))
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )

    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()["pending"]] == [str(assignment.id)]
    assert detail.status_code == 200
    assert detail.json()["items"][0]["question_version_id"] == str(published.id)
    assert detail.json()["items"][0]["prompt"] == "What is 2 + 3?"


def test_answer_save_rejects_stale_version_and_submitted_attempt(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, item, _ = published_assignment_for_student(session)
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )
    attempt_id = detail.json()["attempt"]["id"]
    answer_url = f"/v1/student/attempts/{attempt_id}/answers/{item.id}"

    saved = client.put(
        answer_url,
        headers=authorize(client, student),
        json={"answer": {"value": "5"}, "version": 0},
    )
    conflict = client.put(
        answer_url,
        headers=authorize(client, student),
        json={"answer": {"value": "6"}, "version": 0},
    )

    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert conflict.status_code == 409
    assert conflict.json()["current"]["answer"] == {"value": "5"}


def test_submit_replays_a_matching_idempotency_key(client: TestClient, session: Session) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    headers = authorize(client, student) | {"Idempotency-Key": str(uuid4())}

    first = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=headers)
    retry = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=headers)

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert session.scalar(select(func.count(SubmissionReceipt.id))) == 1
    assert session.scalar(select(StudentAttempt.status)).value == "submitted"
