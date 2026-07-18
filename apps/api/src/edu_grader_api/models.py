from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from .db import Base


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


class VersionStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class TestRunStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    GRADING_ERROR = "grading_error"


class AssignmentStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"


class AttemptStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"


class ReviewTaskStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    SUPERSEDED = "superseded"


class ReviewReason(StrEnum):
    NEEDS_REVIEW = "needs_review"
    AUTO_CONFIRMATION = "auto_confirmation"
    REGRADE_REQUESTED = "regrade_requested"
    RULE_PROBLEM = "rule_problem"


class ReviewAction(StrEnum):
    CONFIRM = "confirm"
    ADJUST_SCORE = "adjust_score"
    REQUEST_REGRADE = "request_regrade"
    REPORT_RULE_PROBLEM = "report_rule_problem"


class AppealStatus(StrEnum):
    OPEN = "open"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


def role_values(roles: type[Role]) -> list[str]:
    return [role.value for role in roles]


def utc_now() -> datetime:
    return datetime.now().astimezone()


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    users: Mapped[list[User]] = relationship(back_populates="tenant")
    classes: Mapped[list[Classroom]] = relationship(back_populates="tenant")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="tenant")
    student_attempts: Mapped[list[StudentAttempt]] = relationship(back_populates="tenant")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "school_id", name="uq_users_tenant_school_id"),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
        CheckConstraint(
            "role != 'student' OR (school_id IS NOT NULL AND work_email IS NULL)",
            name="ck_students_require_school_id_and_no_email",
        ),
        CheckConstraint(
            "(oidc_issuer IS NULL) = (oidc_subject IS NULL)",
            name="ck_oidc_identity_is_complete_or_empty",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    oidc_issuer: Mapped[str | None] = mapped_column(String(500))
    oidc_subject: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, values_callable=role_values), nullable=False
    )
    school_id: Mapped[str | None] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(200))
    work_email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    tenant: Mapped[Tenant] = relationship(back_populates="users")
    taught_classes: Mapped[list[ClassTeacher]] = relationship(back_populates="teacher")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="student")
    created_assignments: Mapped[list[Assignment]] = relationship(
        back_populates="created_by_user", foreign_keys="Assignment.created_by_user_id"
    )
    student_attempts: Mapped[list[StudentAttempt]] = relationship(back_populates="student")
    submission_receipts: Mapped[list[SubmissionReceipt]] = relationship(back_populates="student")


class Classroom(Base):
    __tablename__ = "classes"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_classes_tenant_code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    tenant: Mapped[Tenant] = relationship(back_populates="classes")
    teachers: Mapped[list[ClassTeacher]] = relationship(back_populates="classroom")
    enrollments: Mapped[list[Enrollment]] = relationship(back_populates="classroom")
    assignments: Mapped[list[Assignment]] = relationship(back_populates="classroom")


class ClassTeacher(Base):
    __tablename__ = "class_teachers"

    class_id: Mapped[UUID] = mapped_column(ForeignKey("classes.id"), primary_key=True)
    teacher_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    classroom: Mapped[Classroom] = relationship(back_populates="teachers")
    teacher: Mapped[User] = relationship(back_populates="taught_classes")


class Enrollment(Base):
    __tablename__ = "enrollments"

    class_id: Mapped[UUID] = mapped_column(ForeignKey("classes.id"), primary_key=True)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    classroom: Mapped[Classroom] = relationship(back_populates="enrollments")
    student: Mapped[User] = relationship(back_populates="enrollments")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    event_type: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )


class GradingPolicy(Base):
    __tablename__ = "grading_policies"
    __table_args__ = (
        UniqueConstraint("question_type", "policy_version", name="uq_grading_policy_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_type: Mapped[str] = mapped_column(String(20))
    policy_version: Mapped[str] = mapped_column(String(20))
    json_schema: Mapped[dict[str, object]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question_versions: Mapped[list[QuestionVersion]] = relationship(back_populates="grading_policy")
    grading_runs: Mapped[list[GradingRun]] = relationship(back_populates="grading_policy")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    tenant: Mapped[Tenant] = relationship()
    created_by_user: Mapped[User] = relationship()
    versions: Mapped[list[QuestionVersion]] = relationship(back_populates="question")


class QuestionVersion(Base):
    __tablename__ = "question_versions"
    __table_args__ = (
        UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_id: Mapped[UUID] = mapped_column(ForeignKey("questions.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        Enum(
            VersionStatus,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    prompt: Mapped[str] = mapped_column(String(10_000))
    question_type: Mapped[str] = mapped_column(String(20))
    grading_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("grading_policies.id"), nullable=False
    )
    rule_json: Mapped[dict[str, object]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    question: Mapped[Question] = relationship(back_populates="versions")
    grading_policy: Mapped[GradingPolicy] = relationship(back_populates="question_versions")
    created_by_user: Mapped[User] = relationship(foreign_keys=[created_by_user_id])
    test_cases: Mapped[list[QuestionTestCase]] = relationship(back_populates="question_version")
    test_runs: Mapped[list[QuestionTestRun]] = relationship(back_populates="question_version")
    assignment_items: Mapped[list[AssignmentItem]] = relationship(back_populates="question_version")
    grading_runs: Mapped[list[GradingRun]] = relationship(back_populates="question_version")


class QuestionTestCase(Base):
    __tablename__ = "question_test_cases"
    __table_args__ = (
        UniqueConstraint("question_version_id", "category", name="uq_question_test_case_category"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(30))
    answer_json: Mapped[dict[str, object]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    expected_decision: Mapped[str] = mapped_column(String(30))
    expected_score: Mapped[float] = mapped_column(nullable=False)
    expected_evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    question_version: Mapped[QuestionVersion] = relationship(back_populates="test_cases")


class QuestionTestRun(Base):
    __tablename__ = "question_test_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    grader_version: Mapped[str] = mapped_column(String(100))
    trigger: Mapped[str] = mapped_column(String(30))
    status: Mapped[TestRunStatus] = mapped_column(
        Enum(
            TestRunStatus,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_summary: Mapped[str | None] = mapped_column(String(2_000))

    question_version: Mapped[QuestionVersion] = relationship(back_populates="test_runs")
    case_runs: Mapped[list[QuestionTestCaseRun]] = relationship(back_populates="test_run")


class QuestionTestCaseRun(Base):
    __tablename__ = "question_test_case_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    question_test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_test_runs.id"), nullable=False
    )
    question_test_case_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_test_cases.id"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(30))
    score: Mapped[float] = mapped_column(nullable=False)
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    passed: Mapped[bool] = mapped_column(nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String(2_000))

    test_run: Mapped[QuestionTestRun] = relationship(back_populates="case_runs")


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    class_id: Mapped[UUID] = mapped_column(ForeignKey("classes.id"), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(30))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submission_rule_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus, native_enum=False, values_callable=role_values),
        default=AssignmentStatus.DRAFT,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="assignments")
    classroom: Mapped[Classroom] = relationship(back_populates="assignments")
    created_by_user: Mapped[User] = relationship(
        back_populates="created_assignments", foreign_keys=[created_by_user_id]
    )
    items: Mapped[list[AssignmentItem]] = relationship(back_populates="assignment")
    attempts: Mapped[list[StudentAttempt]] = relationship(back_populates="assignment")
    submission_receipts: Mapped[list[SubmissionReceipt]] = relationship(back_populates="assignment")


class AssignmentItem(Base):
    __tablename__ = "assignment_items"
    __table_args__ = (
        UniqueConstraint("assignment_id", "position", name="uq_assignment_item_position"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    assignment: Mapped[Assignment] = relationship(back_populates="items")
    question_version: Mapped[QuestionVersion] = relationship(back_populates="assignment_items")
    answers: Mapped[list[AttemptAnswer]] = relationship(back_populates="assignment_item")


class StudentAttempt(Base):
    __tablename__ = "student_attempts"
    __table_args__ = (
        UniqueConstraint(
            "assignment_id", "student_id", "attempt_number", name="uq_student_attempt_number"
        ),
        CheckConstraint("attempt_number > 0", name="ck_student_attempt_number_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[AttemptStatus] = mapped_column(
        Enum(AttemptStatus, native_enum=False, values_callable=role_values),
        default=AttemptStatus.DRAFT,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assignment: Mapped[Assignment] = relationship(back_populates="attempts")
    tenant: Mapped[Tenant] = relationship(back_populates="student_attempts")
    student: Mapped[User] = relationship(back_populates="student_attempts")
    answers: Mapped[list[AttemptAnswer]] = relationship(back_populates="attempt")
    grade_publication: Mapped[GradePublication | None] = relationship(back_populates="attempt")


class AttemptAnswer(Base):
    __tablename__ = "attempt_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "assignment_item_id", name="uq_attempt_answer_item"),
        CheckConstraint("version > 0", name="ck_attempt_answer_version_positive"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("student_attempts.id"), nullable=False)
    assignment_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("assignment_items.id"), nullable=False
    )
    answer_json: Mapped[dict[str, object]] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    attempt: Mapped[StudentAttempt] = relationship(back_populates="answers")
    assignment_item: Mapped[AssignmentItem] = relationship(back_populates="answers")
    grading_runs: Mapped[list[GradingRun]] = relationship(back_populates="attempt_answer")
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="attempt_answer")


class GradingRun(Base):
    __tablename__ = "grading_runs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_answers.id"), nullable=False
    )
    question_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("question_versions.id"), nullable=False
    )
    grading_policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("grading_policies.id"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    answer_snapshot_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    max_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False)
    grader_version: Mapped[str] = mapped_column(String(100), nullable=False)
    dependency_versions_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    thresholds_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    attempt_answer: Mapped[AttemptAnswer] = relationship(back_populates="grading_runs")
    question_version: Mapped[QuestionVersion] = relationship(back_populates="grading_runs")
    grading_policy: Mapped[GradingPolicy] = relationship(back_populates="grading_runs")
    signals: Mapped[list[GradingSignal]] = relationship(back_populates="grading_run")
    review_tasks: Mapped[list[ReviewTask]] = relationship(back_populates="grading_run")


class GradingSignal(Base):
    __tablename__ = "grading_signals"
    __table_args__ = (
        UniqueConstraint("grading_run_id", "ordinal", name="uq_grading_signal_run_ordinal"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    grading_run_id: Mapped[UUID] = mapped_column(ForeignKey("grading_runs.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    code: Mapped[str | None] = mapped_column(String(100))
    passed: Mapped[bool | None] = mapped_column(Boolean)
    score: Mapped[float | None] = mapped_column(Float)
    max_score: Mapped[float | None] = mapped_column(Float)
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    grading_run: Mapped[GradingRun] = relationship(back_populates="signals")


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        UniqueConstraint("attempt_answer_id", "active_key", name="uq_review_task_active_answer"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_answer_id: Mapped[UUID] = mapped_column(
        ForeignKey("attempt_answers.id"), nullable=False
    )
    grading_run_id: Mapped[UUID] = mapped_column(ForeignKey("grading_runs.id"), nullable=False)
    reason: Mapped[ReviewReason] = mapped_column(
        Enum(ReviewReason, native_enum=False, values_callable=role_values), nullable=False
    )
    status: Mapped[ReviewTaskStatus] = mapped_column(
        Enum(ReviewTaskStatus, native_enum=False, values_callable=role_values),
        default=ReviewTaskStatus.OPEN,
    )
    active_key: Mapped[str | None] = mapped_column(String(10), default="open")
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    attempt_answer: Mapped[AttemptAnswer] = relationship(back_populates="review_tasks")
    grading_run: Mapped[GradingRun] = relationship(back_populates="review_tasks")
    decisions: Mapped[list[ReviewDecision]] = relationship(back_populates="review_task")


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    review_task_id: Mapped[UUID] = mapped_column(ForeignKey("review_tasks.id"), nullable=False)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[ReviewAction] = mapped_column(
        Enum(ReviewAction, native_enum=False, values_callable=role_values), nullable=False
    )
    original_score: Mapped[float] = mapped_column(Float, nullable=False)
    final_score: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str | None] = mapped_column(String(2_000))
    task_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    review_task: Mapped[ReviewTask] = relationship(back_populates="decisions")


class GradePublication(Base):
    __tablename__ = "grade_publications"
    __table_args__ = (UniqueConstraint("attempt_id", name="uq_grade_publication_attempt"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    attempt_id: Mapped[UUID] = mapped_column(ForeignKey("student_attempts.id"), nullable=False)
    published_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    attempt: Mapped[StudentAttempt] = relationship(back_populates="grade_publication")


class ReviewAppeal(Base):
    __tablename__ = "review_appeals"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    original_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_attempts.id"), nullable=False
    )
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(2_000), nullable=False)
    status: Mapped[AppealStatus] = mapped_column(
        Enum(AppealStatus, native_enum=False, values_callable=role_values),
        default=AppealStatus.OPEN,
    )
    version: Mapped[int] = mapped_column(Integer, default=0)
    decision_reason: Mapped[str | None] = mapped_column(String(2_000))
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CorrectionAttempt(Base):
    __tablename__ = "correction_attempts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    original_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_attempts.id"), nullable=False
    )
    correction_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("student_attempts.id"), nullable=False
    )
    appeal_id: Mapped[UUID] = mapped_column(
        ForeignKey("review_appeals.id"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SubmissionReceipt(Base):
    __tablename__ = "submission_receipts"
    __table_args__ = (
        UniqueConstraint("student_id", "idempotency_key", name="uq_submission_receipt_student_key"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignments.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(36))
    request_fingerprint: Mapped[str] = mapped_column(String(200))
    response_status: Mapped[int] = mapped_column(Integer)
    response_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    tenant: Mapped[Tenant] = relationship()
    student: Mapped[User] = relationship(back_populates="submission_receipts")
    assignment: Mapped[Assignment] = relationship(back_populates="submission_receipts")
