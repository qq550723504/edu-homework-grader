from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates
from sqlalchemy.types import JSON, Uuid

from .db import Base
from .services.question_fingerprints import FINGERPRINT_VERSION, fingerprint_prompt


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


class GuardianConsentStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    GRANTED = "granted"
    WITHDRAWN = "withdrawn"


class PrivacyRequestType(StrEnum):
    ERASURE = "erasure"


class PrivacyRequestStatus(StrEnum):
    REQUESTED = "requested"
    LEGAL_HOLD = "legal_hold"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"


class CurriculumProfileStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class CurriculumRevisionStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class CurriculumImportStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    ACTIVE = "active"
    RETIRED = "retired"


class CurriculumActivityType(StrEnum):
    LEARNING_ACTIVITY = "learning_activity"
    SCORED_QUESTION = "scored_question"


class GenerationJobStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    VALIDATING = "validating"
    READY_FOR_REVIEW = "ready_for_review"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ValidationRunStatus(StrEnum):
    PASSED = "passed"
    WARNING = "warning"
    BLOCKED = "blocked"


class ValidationFindingSeverity(StrEnum):
    WARNING = "warning"
    BLOCKED = "blocked"


ACTIVE_PRIVACY_REQUEST_STATUSES = (
    PrivacyRequestStatus.REQUESTED.value,
    PrivacyRequestStatus.LEGAL_HOLD.value,
    PrivacyRequestStatus.APPROVED.value,
)


def role_values(roles: type[Role]) -> list[str]:
    return [role.value for role in roles]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    signature: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    key_version: Mapped[str] = mapped_column(String(50), nullable=False, default="legacy-unsigned")


class AuditChainHead(Base):
    __tablename__ = "audit_chain_heads"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    latest_entry_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class CurriculumSourceRecord(Base):
    __tablename__ = "curriculum_source_records"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(2_000), nullable=False)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(Date)
    effective_from: Mapped[datetime | None] = mapped_column(Date)
    effective_until: Mapped[datetime | None] = mapped_column(Date)
    editorial_note: Mapped[str | None] = mapped_column(String(1_000))
    license: Mapped[str | None] = mapped_column(String(200))
    document_number: Mapped[str | None] = mapped_column(String(100))
    curated_at: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    profiles: Mapped[list[CurriculumProfile]] = relationship(back_populates="source_record")


class CurriculumProfile(Base):
    __tablename__ = "curriculum_profiles"
    __table_args__ = (UniqueConstraint("code", name="uq_curriculum_profiles_code"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(100), nullable=False)
    version_label: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[CurriculumProfileStatus] = mapped_column(
        Enum(CurriculumProfileStatus, native_enum=False, values_callable=role_values),
        nullable=False,
    )
    source_record_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_source_records.id"), nullable=False
    )
    effective_from: Mapped[datetime | None] = mapped_column(Date)
    effective_until: Mapped[datetime | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    source_record: Mapped[CurriculumSourceRecord] = relationship(back_populates="profiles")
    grade_mappings: Mapped[list[CurriculumGradeMapping]] = relationship(back_populates="profile")
    objectives: Mapped[list[CurriculumObjective]] = relationship(back_populates="profile")
    import_batches: Mapped[list[CurriculumImportBatch]] = relationship(back_populates="profile")


class CurriculumGradeMapping(Base):
    __tablename__ = "curriculum_grade_mappings"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "internal_level", "external_label", name="uq_curriculum_grade_mapping"
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("curriculum_profiles.id"), nullable=False)
    internal_level: Mapped[str] = mapped_column(String(10), nullable=False)
    external_label: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    complexity_rules_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict, nullable=False
    )

    profile: Mapped[CurriculumProfile] = relationship(back_populates="grade_mappings")
    objectives: Mapped[list[CurriculumObjective]] = relationship(back_populates="grade_mapping")


class CurriculumObjective(Base):
    __tablename__ = "curriculum_objectives"
    __table_args__ = (
        UniqueConstraint("profile_id", "code", name="uq_curriculum_objective_code"),
        Index("ix_curriculum_objectives_profile_subject_domain", "profile_id", "subject", "domain"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("curriculum_profiles.id"), nullable=False)
    grade_mapping_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_grade_mappings.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    domain: Mapped[str] = mapped_column(String(200), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(200))
    knowledge_point: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[CurriculumProfileStatus] = mapped_column(
        Enum(CurriculumProfileStatus, native_enum=False, values_callable=role_values),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    profile: Mapped[CurriculumProfile] = relationship(back_populates="objectives")
    grade_mapping: Mapped[CurriculumGradeMapping] = relationship(back_populates="objectives")
    revisions: Mapped[list[CurriculumObjectiveRevision]] = relationship(back_populates="objective")


class CurriculumObjectiveRevision(Base):
    __tablename__ = "curriculum_objective_revisions"
    __table_args__ = (
        UniqueConstraint(
            "objective_id", "revision_number", name="uq_curriculum_objective_revision"
        ),
        CheckConstraint(
            "difficulty_min >= 0 AND difficulty_max <= 1 AND difficulty_min <= difficulty_max",
            name="ck_curriculum_revision_difficulty_range",
        ),
        Index(
            "uq_curriculum_active_revision_per_objective",
            "objective_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    objective_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_objectives.id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(2_000), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(500), nullable=False)
    allowed_question_types: Mapped[list[str]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    difficulty_min: Mapped[float] = mapped_column(Float, nullable=False)
    difficulty_max: Mapped[float] = mapped_column(Float, nullable=False)
    activity_type: Mapped[CurriculumActivityType] = mapped_column(
        Enum(CurriculumActivityType, native_enum=False, values_callable=role_values), nullable=False
    )
    status: Mapped[CurriculumRevisionStatus] = mapped_column(
        Enum(CurriculumRevisionStatus, native_enum=False, values_callable=role_values),
        nullable=False,
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    import_batch_id: Mapped[UUID | None] = mapped_column(ForeignKey("curriculum_import_batches.id"))
    change_summary: Mapped[str | None] = mapped_column(String(1_000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    objective: Mapped[CurriculumObjective] = relationship(back_populates="revisions")
    import_batch: Mapped[CurriculumImportBatch | None] = relationship(
        back_populates="objective_revisions"
    )


class CurriculumPrerequisite(Base):
    __tablename__ = "curriculum_prerequisites"
    __table_args__ = (
        UniqueConstraint(
            "objective_revision_id", "prerequisite_revision_id", name="uq_curriculum_prerequisite"
        ),
        CheckConstraint(
            "objective_revision_id <> prerequisite_revision_id",
            name="ck_curriculum_prerequisite_not_self",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    objective_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_objective_revisions.id"), nullable=False
    )
    prerequisite_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_objective_revisions.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CurriculumImportBatch(Base):
    __tablename__ = "curriculum_import_batches"
    __table_args__ = (
        Index("ix_curriculum_import_batches_profile_status", "profile_id", "status"),
        Index("ix_curriculum_import_batches_digest_status", "content_digest", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    profile_id: Mapped[UUID] = mapped_column(ForeignKey("curriculum_profiles.id"), nullable=False)
    input_format: Mapped[str] = mapped_column(String(10), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[CurriculumImportStatus] = mapped_column(
        Enum(CurriculumImportStatus, native_enum=False, values_callable=role_values),
        nullable=False,
    )
    submitted_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    change_summary: Mapped[str] = mapped_column(String(1_000), nullable=False)
    summary_json: Mapped[dict[str, object]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    profile: Mapped[CurriculumProfile] = relationship(back_populates="import_batches")
    issues: Mapped[list[CurriculumImportIssue]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    objective_revisions: Mapped[list[CurriculumObjectiveRevision]] = relationship(
        back_populates="import_batch"
    )


class CurriculumImportIssue(Base):
    __tablename__ = "curriculum_import_issues"
    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "source_path",
            "source_row",
            "source_column",
            "code",
            name="uq_curriculum_import_issue_location",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_import_batches.id"), nullable=False
    )
    source_path: Mapped[str | None] = mapped_column(String(500))
    source_row: Mapped[int | None] = mapped_column(Integer)
    source_column: Mapped[str | None] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(String(1_000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[CurriculumImportBatch] = relationship(back_populates="issues")


class StudentGuardianConsent(Base):
    __tablename__ = "student_guardian_consents"
    __table_args__ = (
        CheckConstraint(
            "(requires_guardian_consent = false AND status = 'not_required') "
            "OR (requires_guardian_consent = true AND status != 'not_required')",
            name="ck_guardian_consent_status_matches_requirement",
        ),
        CheckConstraint(
            "status != 'granted' OR (notice_version IS NOT NULL "
            "AND evidence_reference IS NOT NULL AND verified_by_user_id IS NOT NULL "
            "AND granted_at IS NOT NULL)",
            name="ck_granted_guardian_consent_has_verification",
        ),
        Index("ix_student_guardian_consents_status", "status"),
    )

    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    requires_guardian_consent: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[GuardianConsentStatus] = mapped_column(
        Enum(GuardianConsentStatus, native_enum=False, values_callable=role_values),
        nullable=False,
    )
    notice_version: Mapped[str | None] = mapped_column(String(50))
    evidence_reference: Mapped[str | None] = mapped_column(String(100))
    verified_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(String(500))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Consent changes are security-sensitive.  Include the version in every
    # UPDATE so concurrent administrators cannot silently overwrite a grant or
    # withdrawal that was committed after they loaded the record.
    __mapper_args__ = {"version_id_col": version, "version_id_generator": False}


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        Index(
            "uq_privacy_requests_active_student",
            "student_id",
            unique=True,
            postgresql_where=text("status IN ('requested', 'legal_hold', 'approved')"),
            sqlite_where=text("status IN ('requested', 'legal_hold', 'approved')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    student_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    request_type: Mapped[PrivacyRequestType] = mapped_column(
        Enum(PrivacyRequestType, native_enum=False, values_callable=role_values), nullable=False
    )
    status: Mapped[PrivacyRequestStatus] = mapped_column(
        Enum(PrivacyRequestStatus, native_enum=False, values_callable=role_values), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    hold_reason: Mapped[str | None] = mapped_column(String(500))
    requested_by_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    decided_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_for_deletion_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class GenerationJob(Base):
    __tablename__ = "generation_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_generation_job_idempotency"),
        CheckConstraint("requested_count > 0", name="ck_generation_job_requested_count_positive"),
        Index("ix_generation_jobs_tenant_status", "tenant_id", "status"),
        Index("ix_generation_jobs_teacher_created", "teacher_user_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenants.id"), nullable=False)
    teacher_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    curriculum_profile_id: Mapped[UUID | None] = mapped_column(ForeignKey("curriculum_profiles.id"))
    curriculum_objective_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("curriculum_objective_revisions.id"), nullable=False
    )
    grade: Mapped[str | None] = mapped_column(String(100))
    subject: Mapped[str | None] = mapped_column(String(100))
    distribution_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GenerationJobStatus] = mapped_column(
        Enum(
            GenerationJobStatus,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str | None] = mapped_column(String(100))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    request_digest: Mapped[str | None] = mapped_column(String(64))
    succeeded_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost_usd: Mapped[float | None] = mapped_column(Float)
    total_duration_ms: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(100))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    tenant: Mapped[Tenant] = relationship()
    teacher: Mapped[User] = relationship(foreign_keys=[teacher_user_id])
    curriculum_profile: Mapped[CurriculumProfile | None] = relationship()
    curriculum_objective_revision: Mapped[CurriculumObjectiveRevision] = relationship()
    attempts: Mapped[list[GenerationAttempt]] = relationship(back_populates="job")
    drafts: Mapped[list[GeneratedQuestionDraft]] = relationship(back_populates="job")
    validation_runs: Mapped[list[GenerationValidationRun]] = relationship(back_populates="job")


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_generation_attempt_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("generation_jobs.id"), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(100), nullable=False)
    seed: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    request_summary: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    response_summary: Mapped[dict[str, object] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    failure_code: Mapped[str | None] = mapped_column(String(100))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    job: Mapped[GenerationJob] = relationship(back_populates="attempts")
    drafts: Mapped[list[GeneratedQuestionDraft]] = relationship(back_populates="generation_attempt")


class GeneratedQuestionDraft(Base):
    __tablename__ = "generated_question_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["current_revision_id", "id"],
            [
                "generated_question_draft_revisions.id",
                "generated_question_draft_revisions.generated_question_draft_id",
            ],
            name="fk_generated_question_drafts_current_revision_pair",
            deferrable=True,
            initially="DEFERRED",
        ),
        UniqueConstraint("job_id", "ordinal", name="uq_generated_question_draft_ordinal"),
        Index("ix_generated_question_drafts_content_hash", "content_hash"),
        Index(
            "ix_generated_question_drafts_job_fingerprint_exact",
            "job_id",
            "fingerprint_version",
            "exact_prompt_hash",
        ),
        Index(
            "ix_generated_question_drafts_job_fingerprint_normalized",
            "job_id",
            "fingerprint_version",
            "normalized_prompt_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    current_revision_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, default=uuid4
    )
    job_id: Mapped[UUID] = mapped_column(ForeignKey("generation_jobs.id"), nullable=False)
    generation_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_attempts.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    fingerprint_version: Mapped[str] = mapped_column(
        String(100), nullable=False, default=FINGERPRINT_VERSION
    )
    exact_prompt_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default=lambda: fingerprint_prompt("").exact_hash
    )
    normalized_prompt_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default=lambda: fingerprint_prompt("").normalized_hash
    )
    validation_errors_json: Mapped[list[dict[str, object]] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql")
    )
    teacher_state: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    job: Mapped[GenerationJob] = relationship(back_populates="drafts")
    generation_attempt: Mapped[GenerationAttempt] = relationship(back_populates="drafts")
    current_revision: Mapped[GeneratedQuestionDraftRevision] = relationship(
        foreign_keys=[current_revision_id], post_update=True
    )
    revisions: Mapped[list[GeneratedQuestionDraftRevision]] = relationship(
        back_populates="draft",
        foreign_keys="GeneratedQuestionDraftRevision.generated_question_draft_id",
        order_by="GeneratedQuestionDraftRevision.revision_number",
    )
    validation_runs: Mapped[list[GenerationValidationRun]] = relationship(
        back_populates="draft",
        order_by="GenerationValidationRun.run_number",
    )

    @validates("candidate_json")
    def _refresh_prompt_fingerprints(self, _key: str, candidate_json: object) -> dict[str, object]:
        prompt = candidate_json.get("prompt") if isinstance(candidate_json, dict) else None
        fingerprints = fingerprint_prompt(prompt if isinstance(prompt, str) else "")
        self.fingerprint_version = fingerprints.version
        self.exact_prompt_hash = fingerprints.exact_hash
        self.normalized_prompt_hash = fingerprints.normalized_hash
        return candidate_json


class GeneratedQuestionDraftRevision(Base):
    __tablename__ = "generated_question_draft_revisions"
    __table_args__ = (
        UniqueConstraint(
            "generated_question_draft_id",
            "revision_number",
            name="uq_generated_question_draft_revision_number",
        ),
        UniqueConstraint(
            "generated_question_draft_id",
            "idempotency_key",
            name="uq_generated_question_draft_revision_idempotency",
        ),
        UniqueConstraint(
            "id",
            "generated_question_draft_id",
            name="uq_generated_question_draft_revision_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    generated_question_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("generated_question_drafts.id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    editor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    # Revision 1 is a system snapshot, created before any teacher write request exists.
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_digest: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped[GeneratedQuestionDraft] = relationship(
        back_populates="revisions", foreign_keys=[generated_question_draft_id]
    )
    editor: Mapped[User | None] = relationship(foreign_keys=[editor_user_id])


class GeneratedQuestionReviewDecision(Base):
    __tablename__ = "generated_question_review_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_revision_id", "generated_question_draft_id"],
            [
                "generated_question_draft_revisions.id",
                "generated_question_draft_revisions.generated_question_draft_id",
            ],
            name="fk_generated_question_review_decisions_revision_pair",
        ),
        ForeignKeyConstraint(
            [
                "generation_validation_run_id",
                "generated_question_draft_id",
                "draft_revision_id",
            ],
            [
                "generation_validation_runs.id",
                "generation_validation_runs.generated_question_draft_id",
                "generation_validation_runs.draft_revision_id",
            ],
            name="fk_generated_question_review_decisions_validation_run_pair",
        ),
        UniqueConstraint(
            "generated_question_draft_id",
            "action",
            "idempotency_key",
            name="uq_generated_question_review_decision_idempotency",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    generated_question_draft_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    draft_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generation_validation_run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(4_000))
    warning_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    accepted_question_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_versions.id")
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft_revision: Mapped[GeneratedQuestionDraftRevision] = relationship(
        foreign_keys=[draft_revision_id]
    )
    validation_run: Mapped[GenerationValidationRun] = relationship(
        foreign_keys=[generation_validation_run_id]
    )
    actor: Mapped[User] = relationship(foreign_keys=[actor_user_id])
    accepted_question_version: Mapped[QuestionVersion | None] = relationship(
        foreign_keys=[accepted_question_version_id]
    )


class GenerationValidationRun(Base):
    __tablename__ = "generation_validation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["draft_revision_id", "generated_question_draft_id"],
            [
                "generated_question_draft_revisions.id",
                "generated_question_draft_revisions.generated_question_draft_id",
            ],
            name="fk_generation_validation_runs_revision_pair",
        ),
        UniqueConstraint(
            "generated_question_draft_id",
            "run_number",
            name="uq_generation_validation_run_draft_number",
        ),
        UniqueConstraint(
            "id",
            "generated_question_draft_id",
            "draft_revision_id",
            name="uq_generation_validation_run_evidence_pair",
        ),
        Index(
            "ix_generation_validation_runs_draft_created",
            "generated_question_draft_id",
            "created_at",
        ),
        Index("ix_generation_validation_runs_job_created", "generation_job_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    generated_question_draft_id: Mapped[UUID] = mapped_column(
        ForeignKey("generated_question_drafts.id"), nullable=False
    )
    draft_revision_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    generation_job_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_jobs.id"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    validator_version: Mapped[str] = mapped_column(String(100), nullable=False)
    ruleset_version: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ValidationRunStatus] = mapped_column(
        Enum(
            ValidationRunStatus,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    feature_summary_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    draft: Mapped[GeneratedQuestionDraft] = relationship(back_populates="validation_runs")
    draft_revision: Mapped[GeneratedQuestionDraftRevision] = relationship(
        foreign_keys=[draft_revision_id]
    )
    job: Mapped[GenerationJob] = relationship(back_populates="validation_runs")
    findings: Mapped[list[ValidationFinding]] = relationship(
        back_populates="validation_run",
        order_by="ValidationFinding.created_at",
    )


class ValidationFinding(Base):
    __tablename__ = "validation_findings"
    __table_args__ = (
        Index("ix_validation_findings_run_created", "validation_run_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    validation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("generation_validation_runs.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[ValidationFindingSeverity] = mapped_column(
        Enum(
            ValidationFindingSeverity,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        nullable=False,
    )
    evidence_json: Mapped[dict[str, object]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    remediation: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    validation_run: Mapped[GenerationValidationRun] = relationship(back_populates="findings")


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
    __table_args__ = (Index("ix_questions_tenant_id", "tenant_id"),)

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
        Index(
            "ix_question_versions_fingerprint_exact",
            "fingerprint_version",
            "exact_prompt_hash",
        ),
        Index(
            "ix_question_versions_fingerprint_normalized",
            "fingerprint_version",
            "normalized_prompt_hash",
        ),
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
    fingerprint_version: Mapped[str] = mapped_column(String(100), nullable=False)
    exact_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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

    @validates("prompt")
    def _refresh_prompt_fingerprints(self, _key: str, prompt: str) -> str:
        fingerprints = fingerprint_prompt(prompt)
        self.fingerprint_version = fingerprints.version
        self.exact_prompt_hash = fingerprints.exact_hash
        self.normalized_prompt_hash = fingerprints.normalized_hash
        return prompt


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
    superseded_by_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("review_tasks.id"))
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
    superseded_by: Mapped[ReviewTask | None] = relationship(remote_side="ReviewTask.id")
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
