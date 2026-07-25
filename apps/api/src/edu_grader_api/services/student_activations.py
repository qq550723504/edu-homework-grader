import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

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
