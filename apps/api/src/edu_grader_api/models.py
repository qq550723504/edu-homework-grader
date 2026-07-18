from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

from .db import Base


class Role(StrEnum):
    ADMIN = "admin"
    TEACHER = "teacher"
    STUDENT = "student"


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
