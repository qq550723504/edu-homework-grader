from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

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
    AttemptStatus,
    AuditLog,
    ClassTeacher,
    Classroom,
    Enrollment,
    GuardianConsentStatus,
    Question,
    QuestionVersion,
    Role,
    StudentAttempt,
    StudentGuardianConsent,
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
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=False,
                status=GuardianConsentStatus.NOT_REQUIRED,
            ),
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


def published_question_version(
    session: Session, *, teacher: User, tenant: Tenant, question_type: str, title: str
) -> QuestionVersion:
    question = Question(tenant=tenant, created_by_user=teacher, title=title)
    version = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt=f"Prompt for {title}",
        question_type=question_type,
        grading_policy_id=uuid4(),
        rule_json={"max_score": 1},
        created_by_user=teacher,
    )
    session.add_all([question, version])
    session.commit()
    return version


def test_teacher_creates_an_ordered_multi_question_assignment_atomically(
    client: TestClient, session: Session
) -> None:
    teacher, _, _, classroom, published_m1, _ = make_classroom_data(session)
    published_m2 = published_question_version(
        session,
        teacher=teacher,
        tenant=classroom.tenant,
        question_type="M2",
        title="Expand x plus one",
    )

    response = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json=assignment_payload(classroom)
        | {"question_version_ids": [str(published_m2.id), str(published_m1.id)]},
    )

    assert response.status_code == 201
    assert response.json()["positions"] == [1, 2]
    assignment = session.get(Assignment, UUID(response.json()["id"]))
    assert assignment is not None
    assert [
        item.question_version_id
        for item in sorted(assignment.items, key=lambda item: item.position)
    ] == [
        published_m2.id,
        published_m1.id,
    ]


def test_teacher_creates_an_ordered_english_assignment_atomically(
    client: TestClient, session: Session
) -> None:
    teacher, _, _, classroom, _, _ = make_classroom_data(session)
    published_e1 = published_question_version(
        session, teacher=teacher, tenant=classroom.tenant, question_type="E1", title="Vocabulary"
    )
    published_e4 = published_question_version(
        session, teacher=teacher, tenant=classroom.tenant, question_type="E4", title="Reading"
    )

    response = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json=assignment_payload(classroom)
        | {
            "subject": "english",
            "question_version_ids": [str(published_e4.id), str(published_e1.id)],
        },
    )

    assert response.status_code == 201
    assert response.json()["positions"] == [1, 2]


@pytest.mark.parametrize("question_version_ids", [[], ["published", "published"], ["english"]])
def test_assignment_composition_rejects_empty_duplicate_and_cross_subject_versions(
    client: TestClient, session: Session, question_version_ids: list[str]
) -> None:
    teacher, _, _, classroom, published_m1, _ = make_classroom_data(session)
    published_e1 = published_question_version(
        session,
        teacher=teacher,
        tenant=classroom.tenant,
        question_type="E1",
        title="Exact answer",
    )
    resolved_ids = [
        str(published_m1.id) if question_id == "published" else str(published_e1.id)
        for question_id in question_version_ids
    ]

    response = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json=assignment_payload(classroom) | {"question_version_ids": resolved_ids},
    )

    assert response.status_code == 422


def test_assigned_teacher_can_publish_a_versioned_assignment(
    client: TestClient, session: Session
) -> None:
    teacher, _, _, classroom, published, _ = make_classroom_data(session)

    created = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json=assignment_payload(classroom) | {"question_version_ids": [str(published.id)]},
    )

    assert created.status_code == 201
    assignment_id = created.json()["id"]
    published_response = client.post(
        f"/v1/assignments/{assignment_id}/publish", headers=authorize(client, teacher)
    )

    assert published_response.status_code == 200
    assert published_response.json()["status"] == AssignmentStatus.PUBLISHED.value


def test_teacher_can_replace_a_draft_composition_but_not_a_published_one(
    client: TestClient, session: Session
) -> None:
    teacher, _, _, classroom, published_m1, _ = make_classroom_data(session)
    published_m2 = published_question_version(
        session,
        teacher=teacher,
        tenant=classroom.tenant,
        question_type="M2",
        title="Expand x plus one",
    )
    created = client.post(
        "/v1/assignments",
        headers=authorize(client, teacher),
        json=assignment_payload(classroom)
        | {"question_version_ids": [str(published_m1.id), str(published_m2.id)]},
    )
    assignment_id = created.json()["id"]

    updated = client.put(
        f"/v1/assignments/{assignment_id}",
        headers=authorize(client, teacher),
        json={
            "title": "Reordered algebra",
            "due_at": datetime(2026, 7, 21, tzinfo=timezone.utc).isoformat(),
            "submission_rule": {"allow_late": True},
            "question_version_ids": [str(published_m2.id), str(published_m1.id)],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["positions"] == [1, 2]
    assignment = session.get(Assignment, UUID(assignment_id))
    assert assignment is not None
    assert assignment.title == "Reordered algebra"
    assert [
        item.question_version_id
        for item in sorted(assignment.items, key=lambda item: item.position)
    ] == [
        published_m2.id,
        published_m1.id,
    ]

    assert (
        client.post(
            f"/v1/assignments/{assignment_id}/publish", headers=authorize(client, teacher)
        ).status_code
        == 200
    )
    frozen = client.put(
        f"/v1/assignments/{assignment_id}",
        headers=authorize(client, teacher),
        json={
            "title": "Should not persist",
            "due_at": datetime(2026, 7, 22, tzinfo=timezone.utc).isoformat(),
            "submission_rule": {"allow_late": False},
            "question_version_ids": [str(published_m1.id)],
        },
    )

    assert frozen.status_code == 409


def test_teacher_lists_only_their_assignments_with_completion_progress(
    client: TestClient, session: Session
) -> None:
    teacher, _, student, classroom, _, _ = make_classroom_data(session)
    assignment = Assignment(
        tenant=classroom.tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Algebra",
        subject="mathematics",
        due_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        submission_rule_json={"allow_late": False},
        status=AssignmentStatus.PUBLISHED,
    )
    session.add(assignment)
    session.flush()
    completed = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment=assignment,
        student=student,
        attempt_number=1,
        status=AttemptStatus.SUBMITTED,
    )
    session.add(completed)
    session.commit()

    response = client.get("/v1/assignments", headers=authorize(client, teacher))

    assert response.status_code == 200
    assert response.json() == {
        "assignments": [
            {
                "id": str(assignment.id),
                "title": "Algebra",
                "subject": "mathematics",
                "class_id": str(classroom.id),
                "class_name": "Year 7 A",
                "due_at": "2026-07-20T00:00:00+00:00",
                "status": "published",
                "student_count": 1,
                "submitted_count": 1,
            }
        ]
    }


def test_unassigned_teacher_and_draft_question_are_rejected(
    client: TestClient, session: Session
) -> None:
    teacher, unassigned_teacher, _, classroom, _, draft = make_classroom_data(session)

    forbidden = client.post(
        "/v1/assignments",
        headers=authorize(client, unassigned_teacher),
        json=assignment_payload(classroom) | {"question_version_ids": [str(draft.id)]},
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
        due_at=datetime.now(timezone.utc) + timedelta(days=1),
        submission_rule_json={"allow_late": False},
        status=AssignmentStatus.PUBLISHED,
        published_at=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )
    item = AssignmentItem(assignment=assignment, question_version=published, position=1)
    session.add_all([assignment, item])
    session.commit()
    return student, classroom, assignment, item, published


def test_published_assignment_fixture_uses_a_future_deadline(session: Session) -> None:
    _, _, assignment, _, _ = published_assignment_for_student(session)

    assert assignment.due_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


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


def test_submitted_unpublished_assignment_remains_pending_review(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    attempt = StudentAttempt(
        tenant_id=student.tenant_id,
        assignment_id=assignment.id,
        student_id=student.id,
        attempt_number=1,
        status=AttemptStatus.SUBMITTED,
        submitted_at=datetime(2026, 7, 19, tzinfo=timezone.utc),
    )
    session.add(attempt)
    session.commit()

    listed = client.get("/v1/student/assignments", headers=authorize(client, student))

    assert listed.status_code == 200
    assert listed.json()["completed"] == []
    assert listed.json()["pending"] == [
        {
            "id": str(assignment.id),
            "title": "Published algebra",
            "subject": "mathematics",
            "due_at": assignment.due_at.replace(tzinfo=timezone.utc).isoformat(),
            "status": "submitted_pending_review",
        }
    ]


@pytest.mark.parametrize(
    ("allow_late", "expected_status"),
    [(False, "overdue"), (True, "late_allowed")],
)
def test_expired_unsubmitted_assignment_exposes_late_policy_status(
    client: TestClient, session: Session, allow_late: bool, expected_status: str
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    assignment.due_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assignment.submission_rule_json = {"allow_late": allow_late}
    session.commit()

    listed = client.get("/v1/student/assignments", headers=authorize(client, student))
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )

    assert listed.status_code == 200
    assert listed.json()["pending"][0]["status"] == expected_status
    assert detail.status_code == 200
    assert detail.json()["status"] == expected_status


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
        json={"answer": {"format": "text-v1", "text": "5"}, "version": 0},
    )
    conflict = client.put(
        answer_url,
        headers=authorize(client, student),
        json={"answer": {"format": "text-v1", "text": "6"}, "version": 0},
    )

    assert saved.status_code == 200
    assert saved.json()["version"] == 1
    assert conflict.status_code == 409
    assert conflict.json()["current"]["answer"] == {"format": "text-v1", "text": "5"}


def test_answer_save_rejects_expired_assignment_when_late_work_is_disabled(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, item, _ = published_assignment_for_student(session)
    assignment.due_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assignment.submission_rule_json = {"allow_late": False}
    session.commit()
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )

    response = client.put(
        f"/v1/student/attempts/{detail.json()['attempt']['id']}/answers/{item.id}",
        headers=authorize(client, student),
        json={"answer": {"format": "text-v1", "text": "5"}, "version": 0},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "assignment_overdue"


def test_submit_rejects_expired_assignment_when_late_work_is_disabled(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    assignment.due_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assignment.submission_rule_json = {"allow_late": False}
    session.commit()

    response = client.post(
        f"/v1/student/assignments/{assignment.id}/submit",
        headers=authorize(client, student) | {"Idempotency-Key": str(uuid4())},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "assignment_overdue"


def test_submit_allows_late_work_and_records_late_audit_evidence(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    assignment.due_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assignment.submission_rule_json = {"allow_late": True}
    session.commit()

    response = client.post(
        f"/v1/student/assignments/{assignment.id}/submit",
        headers=authorize(client, student) | {"Idempotency-Key": str(uuid4())},
    )

    audit = session.scalar(
        select(AuditLog).where(AuditLog.event_type == "student_attempt.submitted")
    )
    assert response.status_code == 200
    assert audit is not None
    assert audit.metadata_json["submitted_late"] is True


def test_answer_save_rejects_legacy_unversioned_envelope(
    client: TestClient, session: Session
) -> None:
    student, _, assignment, item, _ = published_assignment_for_student(session)
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )

    response = client.put(
        f"/v1/student/attempts/{detail.json()['attempt']['id']}/answers/{item.id}",
        headers=authorize(client, student),
        json={"answer": {"value": "5"}, "version": 0},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_answer_envelope"


def test_submit_replays_a_matching_idempotency_key(client: TestClient, session: Session) -> None:
    student, _, assignment, _, _ = published_assignment_for_student(session)
    headers = authorize(client, student) | {"Idempotency-Key": str(uuid4())}

    first = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=headers)
    retry = client.post(f"/v1/student/assignments/{assignment.id}/submit", headers=headers)

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert session.scalar(select(func.count(SubmissionReceipt.id))) == 1
    assert session.scalar(select(StudentAttempt.status)).value == "submitted"
