from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from edu_grader_api.audit import verify_audit_chain
from edu_grader_api.db import Base
from edu_grader_api.models import AuditLog, Role, Tenant, User
from edu_grader_api.services.guardian_consent_integrity import (
    inspect_guardian_consent_integrity,
    repair_missing_guardian_consents,
)


def test_repair_creates_pending_consent_only_for_students_missing_a_record() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        missing = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Missing consent",
        )
        session.add_all([tenant, missing])
        session.commit()

        before = inspect_guardian_consent_integrity(session)

        assert before.missing_student_ids == (missing.id,)
        assert before.contradictory_student_ids == ()

        repaired = repair_missing_guardian_consents(session)
        session.commit()

        assert repaired.created_student_ids == (missing.id,)
        assert inspect_guardian_consent_integrity(session).missing_student_ids == ()
        assert session.scalars(select(AuditLog.event_type)).all() == [
            "guardian_consent.repair_created_pending"
        ]
        assert verify_audit_chain(session, tenant_id=tenant.id).valid
