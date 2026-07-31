from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import CurrentPrincipal
from ..models import ClassTeacher, Classroom, Role, Tenant, User
from .roster import RosterRow, import_roster


class CustomerProvisioningError(ValueError):
    """Raised when a customer configuration conflicts with an existing identity."""


@dataclass(frozen=True)
class CustomerProvisioningResult:
    tenant_id: UUID
    teacher_id: UUID
    class_ids: tuple[UUID, ...]
    imported_students: int


def provision_customer(
    session: Session,
    *,
    tenant_slug: str,
    tenant_name: str,
    oidc_issuer: str,
    teacher_subject: str,
    teacher_display_name: str,
    teacher_email: str,
    rows: list[RosterRow],
) -> CustomerProvisioningResult:
    """Idempotently create a tenant, bind a teacher, and import its roster.

    The teacher identity must already exist in the configured OIDC provider. This
    command deliberately accepts an OIDC subject, not a password or provider
    credential, and leaves one-time student activation issuance to the teacher
    workflow.
    """
    values = {
        "tenant_slug": tenant_slug.strip(),
        "tenant_name": tenant_name.strip(),
        "oidc_issuer": oidc_issuer.strip(),
        "teacher_subject": teacher_subject.strip(),
        "teacher_display_name": teacher_display_name.strip(),
        "teacher_email": teacher_email.strip().lower(),
    }
    if not all(values.values()):
        raise CustomerProvisioningError("tenant and teacher identity fields are required")
    if not rows:
        raise CustomerProvisioningError("roster must contain at least one student")

    tenant = session.scalar(select(Tenant).where(Tenant.slug == values["tenant_slug"]))
    if tenant is None:
        tenant = Tenant(slug=values["tenant_slug"], name=values["tenant_name"])
        session.add(tenant)
        session.flush()
    else:
        tenant.name = values["tenant_name"]

    identity = session.scalar(
        select(User).where(
            User.oidc_issuer == values["oidc_issuer"],
            User.oidc_subject == values["teacher_subject"],
        )
    )
    if identity is not None and identity.tenant_id != tenant.id:
        raise CustomerProvisioningError("teacher identity belongs to another tenant")
    teacher = identity
    if teacher is None:
        teacher = session.scalar(
            select(User).where(
                User.tenant_id == tenant.id,
                User.work_email == values["teacher_email"],
            )
        )
        if teacher is not None and teacher.oidc_subject != values["teacher_subject"]:
            raise CustomerProvisioningError("teacher email is already bound to another identity")
    if teacher is None:
        teacher = User(
            tenant=tenant,
            role=Role.TEACHER,
            oidc_issuer=values["oidc_issuer"],
            oidc_subject=values["teacher_subject"],
            display_name=values["teacher_display_name"],
            work_email=values["teacher_email"],
        )
        session.add(teacher)
        session.flush()
    elif teacher.role is not Role.TEACHER:
        raise CustomerProvisioningError("existing OIDC identity is not a teacher")
    else:
        teacher.display_name = values["teacher_display_name"]
        teacher.work_email = values["teacher_email"]

    class_ids: list[UUID] = []
    for class_code, class_name in sorted({(row.class_code, row.class_name) for row in rows}):
        classroom = session.scalar(
            select(Classroom).where(
                Classroom.tenant_id == tenant.id,
                Classroom.code == class_code,
            )
        )
        if classroom is None:
            classroom = Classroom(tenant_id=tenant.id, code=class_code, name=class_name)
            session.add(classroom)
            session.flush()
        else:
            classroom.name = class_name
        if session.get(ClassTeacher, (classroom.id, teacher.id)) is None:
            session.add(ClassTeacher(class_id=classroom.id, teacher_id=teacher.id))
        class_ids.append(classroom.id)

    session.commit()
    imported_students = import_roster(
        session,
        CurrentPrincipal(
            user_id=str(teacher.id),
            tenant_id=str(tenant.id),
            role=Role.TEACHER,
            school_id=None,
            display_name=teacher.display_name,
            oidc_subject=teacher.oidc_subject or "",
        ),
        rows,
    )
    return CustomerProvisioningResult(
        tenant_id=tenant.id,
        teacher_id=teacher.id,
        class_ids=tuple(class_ids),
        imported_students=imported_students,
    )
