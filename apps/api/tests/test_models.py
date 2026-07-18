import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import Base, Role, Tenant, User


def test_student_school_id_is_unique_within_a_tenant() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot-a", name="Pilot A")
        session.add_all(
            [
                tenant,
                User(
                    tenant=tenant,
                    role=Role.STUDENT,
                    school_id="S-001",
                    display_name="One",
                ),
                User(
                    tenant=tenant,
                    role=Role.STUDENT,
                    school_id="S-001",
                    display_name="Two",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


@pytest.mark.parametrize(
    ("school_id", "work_email"),
    [(None, None), ("S-002", "student@example.test")],
)
def test_student_requires_school_id_and_has_no_work_email(
    school_id: str | None, work_email: str | None
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot-b", name="Pilot B")
        session.add_all(
            [
                tenant,
                User(
                    tenant=tenant,
                    role=Role.STUDENT,
                    school_id=school_id,
                    work_email=work_email,
                    display_name="Student",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_oidc_identity_requires_issuer_and_subject_together() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot-c", name="Pilot C")
        session.add_all(
            [
                tenant,
                User(
                    tenant=tenant,
                    role=Role.TEACHER,
                    oidc_issuer="https://issuer.example.test",
                    display_name="Teacher",
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()
