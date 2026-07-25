import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Classroom, StudentActivation, StudentActivationStatus, User
from ..settings import settings


def activation_code_hmac(code: str) -> str:
    return hmac.new(
        settings.student_activation_hmac_key.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_activation_code() -> str:
    return secrets.token_urlsafe(24)


class StudentProvisioner(Protocol):
    def ensure_student(self, *, school_id: str, display_name: str, activation_code: str) -> str: ...
    def disable_temporary_password(self, keycloak_user_id: str) -> None: ...


@dataclass(frozen=True)
class IssuedActivation:
    activation_id: object
    code: str


def issue_activation(
    session: Session,
    *,
    teacher: User,
    classroom: Classroom,
    student: User,
    keycloak: StudentProvisioner,
    now: datetime,
) -> IssuedActivation:
    if student.oidc_subject is not None or not student.school_id:
        raise ValueError("student is not eligible for activation")
    previous = session.scalar(
        select(StudentActivation)
        .where(
            StudentActivation.student_id == student.id,
            StudentActivation.status == StudentActivationStatus.ISSUED,
        )
        .with_for_update()
    )
    if previous is not None:
        previous.status = StudentActivationStatus.REVOKED
        previous.revoked_at = now
    code = generate_activation_code()
    activation = StudentActivation(
        student_id=student.id,
        class_id=classroom.id,
        status=StudentActivationStatus.PROVISIONING,
        issued_by_user_id=teacher.id,
    )
    session.add(activation)
    session.flush()
    activation.keycloak_user_id = keycloak.ensure_student(
        school_id=student.school_id, display_name=student.display_name, activation_code=code
    )
    activation.code_hmac = activation_code_hmac(code)
    activation.status = StudentActivationStatus.ISSUED
    activation.issued_at = now
    activation.disclosed_at = now
    activation.expires_at = now + timedelta(days=settings.student_activation_expiry_days)
    session.commit()
    return IssuedActivation(activation_id=activation.id, code=code)


def consume_pending_activation(session: Session, *, student: User, now: datetime) -> bool:
    activation = session.scalar(
        select(StudentActivation)
        .where(
            StudentActivation.student_id == student.id,
            StudentActivation.status == StudentActivationStatus.ISSUED,
        )
        .with_for_update()
    )
    if activation is None:
        return True
    if activation.expires_at is None or activation.expires_at <= now:
        activation.status = StudentActivationStatus.EXPIRED
        activation.expired_at = now
        session.commit()
        return False
    activation.status = StudentActivationStatus.CONSUMED
    activation.consumed_at = now
    session.commit()
    return True


def expire_activations(session: Session, *, keycloak: StudentProvisioner, now: datetime) -> int:
    expired = list(session.scalars(select(StudentActivation).where(
        StudentActivation.status == StudentActivationStatus.ISSUED,
        StudentActivation.expires_at <= now,
    )))
    for activation in expired:
        if activation.keycloak_user_id:
            keycloak.disable_temporary_password(activation.keycloak_user_id)
        activation.status = StudentActivationStatus.EXPIRED
        activation.expired_at = now
    session.commit()
    return len(expired)
