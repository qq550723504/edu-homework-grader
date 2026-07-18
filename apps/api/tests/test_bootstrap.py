from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.bootstrap import bootstrap_admin
from edu_grader_api.models import Base, Role


def test_bootstrap_admin_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first = bootstrap_admin(
            session,
            issuer="http://keycloak:8080/realms/edu-grader",
            subject="admin-subject",
            tenant_slug="pilot",
        )
        second = bootstrap_admin(
            session,
            issuer="http://keycloak:8080/realms/edu-grader",
            subject="admin-subject",
            tenant_slug="pilot",
        )

        assert first.id == second.id
        assert second.role is Role.ADMIN
