from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from edu_grader_api.audit import append_audit_event, verify_audit_chain
from edu_grader_api.db import Base
from edu_grader_api.models import (
    AppealStatus,
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    AttemptAnswer,
    ClassTeacher,
    Classroom,
    CorrectionAttempt,
    Enrollment,
    GradePublication,
    GradingPolicy,
    GradingRun,
    GradingSignal,
    GuardianConsentStatus,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Question,
    QuestionVersion,
    ReviewAction,
    ReviewAppeal,
    ReviewDecision,
    ReviewReason,
    ReviewTask,
    Role,
    StudentAttempt,
    StudentGuardianConsent,
    SubmissionReceipt,
    Tenant,
    User,
    VersionStatus,
    utc_now,
)
from edu_grader_api.services.privacy_cleanup import (
    PrivacyCleanupSkipped,
    complete_privacy_request,
    eligible_privacy_requests,
)


def approved_request_with_attempt_graph(
    session: Session, *, eligible_at
) -> tuple[PrivacyRequest, User, StudentAttempt, User, Tenant]:
    tenant = Tenant(slug="pilot", name="Pilot")
    admin = User(tenant=tenant, role=Role.ADMIN, display_name="Administrator")
    teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Teacher")
    student = User(
        tenant=tenant,
        role=Role.STUDENT,
        school_id="S-001",
        oidc_issuer="https://issuer.example.test",
        oidc_subject="student-subject",
        display_name="Student",
    )
    classroom = Classroom(tenant=tenant, code="7A", name="Year 7 A")
    policy = GradingPolicy(question_type="M1", policy_version="1", json_schema={})
    session.add_all([tenant, admin, teacher, student, classroom, policy])
    session.flush()
    session.add(ClassTeacher(class_id=classroom.id, teacher_id=teacher.id))
    session.add(Enrollment(class_id=classroom.id, student_id=student.id))
    question = Question(tenant=tenant, created_by_user=teacher, title="Addition")
    session.add(question)
    session.flush()
    version = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt="What is 2 + 3?",
        question_type="M1",
        grading_policy=policy,
        rule_json={"expected": 5},
        created_by_user=teacher,
    )
    assignment = Assignment(
        tenant=tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Algebra",
        subject="mathematics",
        due_at=utc_now(),
        submission_rule_json={},
        status=AssignmentStatus.PUBLISHED,
    )
    session.add_all([version, assignment])
    session.flush()
    item = AssignmentItem(assignment=assignment, question_version=version, position=1)
    original = StudentAttempt(
        tenant=tenant,
        assignment=assignment,
        student=student,
        attempt_number=1,
    )
    correction = StudentAttempt(
        tenant=tenant,
        assignment=assignment,
        student=student,
        attempt_number=2,
    )
    session.add_all([item, original, correction])
    session.flush()
    answer = AttemptAnswer(
        attempt=original,
        assignment_item=item,
        answer_json={"value": "5"},
        version=1,
    )
    session.add(answer)
    session.flush()
    run = GradingRun(
        attempt_answer=answer,
        question_version=version,
        grading_policy=policy,
        policy_version="1",
        rule_snapshot_json={},
        answer_snapshot_json={"value": "5"},
        decision="accepted",
        score=1,
        max_score=1,
        confidence=1,
        requires_review=True,
        grader_version="test",
        dependency_versions_json={},
        thresholds_json={},
        evidence_json={},
    )
    session.add(run)
    session.flush()
    task = ReviewTask(
        attempt_answer=answer,
        grading_run=run,
        reason=ReviewReason.NEEDS_REVIEW,
    )
    appeal = ReviewAppeal(
        original_attempt_id=original.id,
        student_id=student.id,
        reason="Review",
        status=AppealStatus.APPROVED,
    )
    session.add_all([task, appeal])
    session.flush()
    session.add_all(
        [
            GradingSignal(
                grading_run=run,
                ordinal=0,
                kind="criterion",
                evidence_json={},
            ),
            ReviewDecision(
                review_task=task,
                actor_user_id=teacher.id,
                action=ReviewAction.CONFIRM,
                original_score=1,
                final_score=1,
                task_version=0,
            ),
            GradePublication(attempt=original, published_by_user_id=teacher.id),
            CorrectionAttempt(
                original_attempt_id=original.id,
                correction_attempt_id=correction.id,
                appeal_id=appeal.id,
            ),
            SubmissionReceipt(
                tenant=tenant,
                student=student,
                assignment=assignment,
                idempotency_key="00000000-0000-0000-0000-000000000001",
                request_fingerprint="attempt",
                response_status=200,
                response_json={},
            ),
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=False,
                status=GuardianConsentStatus.NOT_REQUIRED,
            ),
        ]
    )
    request = PrivacyRequest(
        tenant_id=tenant.id,
        student_id=student.id,
        request_type=PrivacyRequestType.ERASURE,
        status=PrivacyRequestStatus.APPROVED,
        reason="school request",
        requested_by_user_id=admin.id,
        decided_by_user_id=admin.id,
        requested_at=utc_now() - timedelta(days=2),
        decided_at=utc_now() - timedelta(days=1),
        eligible_for_deletion_at=eligible_at,
        version=1,
    )
    session.add(request)
    session.flush()
    append_audit_event(
        session,
        tenant_id=tenant.id,
        actor_user_id=student.id,
        event_type="student_attempt.submitted",
        target_type="student_attempt",
        target_id=original.id,
        metadata={},
    )
    session.commit()
    return request, student, original, admin, tenant


def test_cleanup_dry_run_leaves_every_record_unchanged() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        request, student, _, _, _ = approved_request_with_attempt_graph(
            session, eligible_at=utc_now() - timedelta(seconds=1)
        )

        candidates = eligible_privacy_requests(session, now=utc_now())

        assert [candidate.id for candidate in candidates] == [request.id]
        assert session.get(User, student.id).school_id == "S-001"


def test_execute_cleanup_deletes_operational_graph_and_deidentifies_user() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        request, student, attempt, admin, tenant = approved_request_with_attempt_graph(
            session, eligible_at=utc_now() - timedelta(seconds=1)
        )
        student_id = student.id
        attempt_id = attempt.id

        result = complete_privacy_request(
            session,
            request_id=request.id,
            actor_user_id=admin.id,
            now=utc_now(),
        )
        session.commit()

        assert result.status is PrivacyRequestStatus.COMPLETED
        assert session.get(StudentAttempt, attempt_id) is None
        assert session.scalar(select(AttemptAnswer.id)) is None
        assert session.scalar(select(GradingRun.id)) is None
        assert session.scalar(select(ReviewAppeal.id)) is None
        assert session.scalar(select(SubmissionReceipt.id)) is None
        assert session.get(StudentGuardianConsent, student_id) is None
        erased = session.get(User, student_id)
        assert erased is not None
        assert erased.oidc_issuer is None and erased.oidc_subject is None
        assert erased.school_id == f"erased-{student_id}"
        assert verify_audit_chain(session, tenant_id=tenant.id).valid is True


def test_future_dated_request_is_not_cleaned() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        request, student, attempt, admin, _ = approved_request_with_attempt_graph(
            session, eligible_at=utc_now() + timedelta(days=1)
        )

        with pytest.raises(PrivacyCleanupSkipped):
            complete_privacy_request(
                session,
                request_id=request.id,
                actor_user_id=admin.id,
                now=utc_now(),
            )

        assert session.get(StudentAttempt, attempt.id) is not None
        assert session.get(User, student.id).school_id == "S-001"
