import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from edu_grader_api.db import Base
from edu_grader_api.models import Role, Tenant, User
from edu_grader_api import guardian_consent_integrity


def test_guardian_consent_integrity_command_is_read_only_without_execute(
    monkeypatch, capsys
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        student = User(
            tenant=tenant,
            role=Role.STUDENT,
            school_id="S-001",
            display_name="Missing consent",
        )
        session.add_all([tenant, student])
        session.commit()
        student_id = student.id

    monkeypatch.setattr(guardian_consent_integrity, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(sys, "argv", ["guardian-consent-integrity"])

    assert guardian_consent_integrity.main() == 0

    assert capsys.readouterr().out.splitlines() == [
        f"missing={student_id}",
        "contradictory=",
    ]
