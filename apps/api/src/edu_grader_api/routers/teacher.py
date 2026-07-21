from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..db import get_session
from ..dependencies import require_role
from ..models import ClassTeacher, Classroom, Enrollment, GuardianConsentStatus, Role, User
from ..services.roster import (
    RosterRow,
    RosterValidationError,
    import_teacher_roster,
    parse_roster,
    validate_consent_fields,
)


router = APIRouter(prefix="/v1/teacher", tags=["teacher"])


class CreateClassRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)


class CreateStudentRequest(BaseModel):
    school_id: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    under_14: bool
    guardian_consent_status: GuardianConsentStatus
    guardian_consent_notice_version: str | None = Field(default=None, max_length=50)
    guardian_consent_evidence_reference: str | None = Field(default=None, max_length=100)


class UpdateStudentRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)


def owned_class_or_404(session: Session, principal: CurrentPrincipal, class_id: UUID) -> Classroom:
    classroom = session.scalar(
        select(Classroom).where(
            Classroom.id == class_id, Classroom.tenant_id == UUID(principal.tenant_id)
        )
    )
    if classroom is None or session.get(ClassTeacher, (class_id, UUID(principal.user_id))) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return classroom


def enrolled_student_or_404(
    session: Session, principal: CurrentPrincipal, class_id: UUID, student_id: UUID
) -> tuple[User, Enrollment]:
    owned_class_or_404(session, principal, class_id)
    student = session.scalar(
        select(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .where(
            Enrollment.class_id == class_id,
            User.id == student_id,
            User.tenant_id == UUID(principal.tenant_id),
            User.role == Role.STUDENT,
        )
    )
    enrollment = session.get(Enrollment, (class_id, student_id))
    if student is None or enrollment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")
    return student, enrollment


def raise_roster_validation_error(error: RosterValidationError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
    ) from error


@router.get("/classes")
def list_classes(
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    rows = session.execute(
        select(Classroom, func.count(Enrollment.student_id))
        .join(ClassTeacher, ClassTeacher.class_id == Classroom.id)
        .outerjoin(Enrollment, Enrollment.class_id == Classroom.id)
        .where(
            Classroom.tenant_id == UUID(principal.tenant_id),
            ClassTeacher.teacher_id == UUID(principal.user_id),
        )
        .group_by(Classroom.id)
        .order_by(Classroom.code)
    ).all()
    return {
        "items": [
            {
                "id": str(classroom.id),
                "code": classroom.code,
                "name": classroom.name,
                "student_count": student_count,
            }
            for classroom, student_count in rows
        ]
    }


@router.post("/classes", status_code=status.HTTP_201_CREATED)
def create_class(
    body: CreateClassRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str | int]:
    session.rollback()
    try:
        with session.begin():
            if (
                session.scalar(
                    select(Classroom.id).where(
                        Classroom.tenant_id == UUID(principal.tenant_id),
                        Classroom.code == body.code,
                    )
                )
                is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="class code already exists"
                )
            classroom = Classroom(
                tenant_id=UUID(principal.tenant_id),
                code=body.code,
                name=body.name,
            )
            session.add(classroom)
            session.flush()
            session.add(ClassTeacher(class_id=classroom.id, teacher_id=UUID(principal.user_id)))
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="class.created",
                target_type="class",
                target_id=classroom.id,
                metadata={},
            )
            append_audit_event(
                session,
                tenant_id=UUID(principal.tenant_id),
                actor_user_id=UUID(principal.user_id),
                event_type="class.teacher_assigned",
                target_type="class",
                target_id=classroom.id,
                metadata={"teacher_id": principal.user_id},
            )
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="class code already exists"
        ) from error
    return {
        "id": str(classroom.id),
        "code": classroom.code,
        "name": classroom.name,
        "student_count": 0,
    }


@router.get("/classes/{class_id}/students")
def list_students(
    class_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, object]:
    owned_class_or_404(session, principal, class_id)
    students = list(
        session.scalars(
            select(User)
            .join(Enrollment, Enrollment.student_id == User.id)
            .where(
                Enrollment.class_id == class_id,
                User.tenant_id == UUID(principal.tenant_id),
                User.role == Role.STUDENT,
            )
            .order_by(User.school_id, User.id)
        )
    )
    return {
        "items": [
            {
                "id": str(student.id),
                "school_id": student.school_id,
                "display_name": student.display_name,
            }
            for student in students
        ]
    }


@router.post("/classes/{class_id}/students", status_code=status.HTTP_201_CREATED)
def create_student(
    class_id: UUID,
    body: CreateStudentRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, int]:
    classroom = owned_class_or_404(session, principal, class_id)
    try:
        validate_consent_fields(
            row_number=1,
            requires_guardian_consent=body.under_14,
            status=body.guardian_consent_status,
            notice_version=body.guardian_consent_notice_version or "",
            evidence_reference=body.guardian_consent_evidence_reference or "",
        )
        imported = import_teacher_roster(
            session,
            principal,
            class_id,
            [
                RosterRow(
                    class_code=classroom.code,
                    class_name=classroom.name,
                    student_school_id=body.school_id,
                    student_display_name=body.display_name,
                    requires_guardian_consent=body.under_14,
                    guardian_consent_status=body.guardian_consent_status,
                    guardian_consent_notice_version=body.guardian_consent_notice_version,
                    guardian_consent_evidence_reference=body.guardian_consent_evidence_reference,
                )
            ],
        )
    except RosterValidationError as error:
        raise_roster_validation_error(error)
    return {"imported": imported}


@router.patch("/classes/{class_id}/students/{student_id}")
def update_student(
    class_id: UUID,
    student_id: UUID,
    body: UpdateStudentRequest,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, str]:
    session.rollback()
    with session.begin():
        student, _ = enrolled_student_or_404(session, principal, class_id, student_id)
        student.display_name = body.display_name
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="roster.student_name_updated",
            target_type="student",
            target_id=student.id,
            metadata={"class_id": str(class_id)},
        )
    return {
        "id": str(student.id),
        "school_id": student.school_id or "",
        "display_name": student.display_name,
    }


@router.delete("/classes/{class_id}/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_student(
    class_id: UUID,
    student_id: UUID,
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    session.rollback()
    with session.begin():
        student, enrollment = enrolled_student_or_404(session, principal, class_id, student_id)
        session.delete(enrollment)
        append_audit_event(
            session,
            tenant_id=UUID(principal.tenant_id),
            actor_user_id=UUID(principal.user_id),
            event_type="roster.student_removed",
            target_type="student",
            target_id=student.id,
            metadata={"class_id": str(class_id)},
        )


@router.post("/classes/{class_id}/students/import")
async def import_students(
    class_id: UUID,
    file: Annotated[UploadFile, File(...)],
    principal: Annotated[CurrentPrincipal, Depends(require_role(Role.TEACHER))],
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, int]:
    classroom = owned_class_or_404(session, principal, class_id)
    try:
        rows = parse_roster(await file.read())
        if any(
            row.class_code != classroom.code or row.class_name != classroom.name for row in rows
        ):
            raise RosterValidationError("CSV class does not match selected class")
        return {"imported": import_teacher_roster(session, principal, class_id, rows)}
    except RosterValidationError as error:
        raise_roster_validation_error(error)
