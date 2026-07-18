from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Assignment,
    AssignmentItem,
    AttemptAnswer,
    Classroom,
    Role,
    StudentAttempt,
    SubmissionReceipt,
    Tenant,
    User,
)


def _assignment(session: Session) -> tuple[Assignment, User]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Teacher")
    student = User(tenant=tenant, role=Role.STUDENT, school_id="S-001", display_name="Student")
    classroom = Classroom(tenant=tenant, code="7A", name="Year 7 A")
    assignment = Assignment(
        tenant=tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Algebra",
        subject="mathematics",
        due_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        submission_rule_json={"allow_late": False},
    )
    session.add_all([tenant, teacher, student, classroom, assignment])
    session.flush()
    return assignment, student


def test_assignment_item_position_is_unique() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    from edu_grader_api.db import Base

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        assignment, _ = _assignment(session)
        session.add_all(
            [
                AssignmentItem(assignment=assignment, question_version_id=uuid4(), position=1),
                AssignmentItem(assignment=assignment, question_version_id=uuid4(), position=1),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_answer_and_submission_receipt_have_scoped_unique_keys() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    from edu_grader_api.db import Base

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        assignment, student = _assignment(session)
        item = AssignmentItem(assignment=assignment, question_version_id=uuid4(), position=1)
        attempt = StudentAttempt(
            tenant=assignment.tenant,
            assignment=assignment,
            student=student,
            attempt_number=1,
        )
        session.add_all([item, attempt])
        session.flush()
        session.add_all(
            [
                AttemptAnswer(
                    attempt=attempt,
                    assignment_item=item,
                    answer_json={"value": "5"},
                    version=1,
                ),
                AttemptAnswer(
                    attempt=attempt,
                    assignment_item=item,
                    answer_json={"value": "6"},
                    version=1,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()

    with Session(engine) as session:
        assignment, student = _assignment(session)
        session.add_all(
            [
                SubmissionReceipt(
                    tenant=assignment.tenant,
                    student=student,
                    assignment=assignment,
                    idempotency_key="ee8e9636-d2c2-4a1e-a4f2-33cee998f3d2",
                    request_fingerprint="attempt:1",
                    response_status=200,
                    response_json={"status": "submitted"},
                ),
                SubmissionReceipt(
                    tenant=assignment.tenant,
                    student=student,
                    assignment=assignment,
                    idempotency_key="ee8e9636-d2c2-4a1e-a4f2-33cee998f3d2",
                    request_fingerprint="attempt:1",
                    response_status=200,
                    response_json={"status": "submitted"},
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
