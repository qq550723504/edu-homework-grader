import csv
from dataclasses import dataclass
from io import StringIO
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import append_audit_event
from ..auth import CurrentPrincipal
from ..models import Classroom, Enrollment, Role, User


EXPECTED_HEADERS = {"class_code", "class_name", "student_school_id", "student_display_name"}


class RosterValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RosterRow:
    class_code: str
    class_name: str
    student_school_id: str
    student_display_name: str


def parse_roster(data: bytes) -> list[RosterRow]:
    try:
        reader = csv.DictReader(StringIO(data.decode("utf-8-sig")))
    except UnicodeDecodeError as error:
        raise RosterValidationError("CSV must be UTF-8") from error
    if set(reader.fieldnames or []) != EXPECTED_HEADERS:
        raise RosterValidationError("CSV has invalid headers")

    rows: list[RosterRow] = []
    seen_students: set[str] = set()
    class_names: dict[str, str] = {}
    for row_number, record in enumerate(reader, start=2):
        values = {key: (record.get(key) or "").strip() for key in EXPECTED_HEADERS}
        if not all(values.values()):
            raise RosterValidationError(f"row {row_number} has a blank required value")
        student_id = values["student_school_id"]
        if student_id in seen_students:
            raise RosterValidationError(f"row {row_number} repeats student_school_id")
        seen_students.add(student_id)
        code = values["class_code"]
        if code in class_names and class_names[code] != values["class_name"]:
            raise RosterValidationError(f"row {row_number} conflicts with the class name")
        class_names[code] = values["class_name"]
        rows.append(RosterRow(**values))
    if not rows:
        raise RosterValidationError("CSV has no data rows")
    return rows


def import_roster(session: Session, actor: CurrentPrincipal, rows: list[RosterRow]) -> int:
    """Atomically create tenant-local roster records and their audit events."""
    session.rollback()
    with session.begin():
        for row in rows:
            classroom = session.scalar(
                select(Classroom).where(
                    Classroom.tenant_id == UUID(actor.tenant_id), Classroom.code == row.class_code
                )
            )
            if classroom is None:
                classroom = Classroom(
                    tenant_id=UUID(actor.tenant_id), code=row.class_code, name=row.class_name
                )
                session.add(classroom)
                session.flush()

            student = session.scalar(
                select(User).where(
                    User.tenant_id == UUID(actor.tenant_id), User.school_id == row.student_school_id
                )
            )
            if student is None:
                student = User(
                    tenant_id=UUID(actor.tenant_id),
                    role=Role.STUDENT,
                    school_id=row.student_school_id,
                    display_name=row.student_display_name,
                )
                session.add(student)
                session.flush()
            else:
                student.display_name = row.student_display_name

            enrollment = session.get(Enrollment, (classroom.id, student.id))
            if enrollment is None:
                session.add(Enrollment(class_id=classroom.id, student_id=student.id))
            append_audit_event(
                session,
                tenant_id=UUID(actor.tenant_id),
                actor_user_id=UUID(actor.user_id),
                event_type="roster.imported",
                target_type="student",
                target_id=student.id,
                metadata={"class_id": str(classroom.id)},
            )
    return len(rows)
