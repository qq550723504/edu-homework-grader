import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    PrivacyRequest,
    PrivacyRequestStatus,
    PrivacyRequestType,
    Role,
    Tenant,
    User,
)


def test_only_one_active_erasure_request_exists_for_a_student() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        admin = User(tenant=tenant, role=Role.ADMIN, display_name="Administrator")
        student = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Student",
        )
        session.add_all([tenant, admin, student])
        session.flush()
        session.add_all(
            [
                PrivacyRequest(
                    tenant_id=tenant.id,
                    student_id=student.id,
                    request_type=PrivacyRequestType.ERASURE,
                    status=PrivacyRequestStatus.REQUESTED,
                    reason="school request",
                    requested_by_user_id=admin.id,
                ),
                PrivacyRequest(
                    tenant_id=tenant.id,
                    student_id=student.id,
                    request_type=PrivacyRequestType.ERASURE,
                    status=PrivacyRequestStatus.APPROVED,
                    reason="school request",
                    requested_by_user_id=admin.id,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_rejected_request_does_not_block_a_later_active_request() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        admin = User(tenant=tenant, role=Role.ADMIN, display_name="Administrator")
        student = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Student",
        )
        session.add_all([tenant, admin, student])
        session.flush()
        session.add_all(
            [
                PrivacyRequest(
                    tenant_id=tenant.id,
                    student_id=student.id,
                    request_type=PrivacyRequestType.ERASURE,
                    status=PrivacyRequestStatus.REJECTED,
                    reason="school request",
                    requested_by_user_id=admin.id,
                ),
                PrivacyRequest(
                    tenant_id=tenant.id,
                    student_id=student.id,
                    request_type=PrivacyRequestType.ERASURE,
                    status=PrivacyRequestStatus.REQUESTED,
                    reason="new school request",
                    requested_by_user_id=admin.id,
                ),
            ]
        )

        session.commit()
