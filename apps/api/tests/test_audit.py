from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.audit import append_audit_event, verify_audit_chain
from edu_grader_api.models import Base, Role, Tenant, User


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_append_links_and_signs_a_tenant_ledger() -> None:
    session = _session()
    tenant = Tenant(slug="pilot", name="Pilot")
    session.add(tenant)
    session.flush()
    teacher = User(tenant_id=tenant.id, role=Role.TEACHER, display_name="Teacher")
    session.add(teacher)
    session.flush()

    first = append_audit_event(
        session,
        tenant_id=tenant.id,
        actor_user_id=teacher.id,
        event_type="question.rule_changed",
        target_type="question_version",
        target_id=uuid4(),
        metadata={"version_number": 2},
    )
    second = append_audit_event(
        session,
        tenant_id=tenant.id,
        actor_user_id=teacher.id,
        event_type="grade.published",
        target_type="student_attempt",
        target_id=uuid4(),
        metadata={"assignment_id": str(uuid4())},
    )

    assert (first.sequence, second.sequence) == (1, 2)
    assert second.previous_hash == first.entry_hash
    assert verify_audit_chain(session, tenant_id=tenant.id).valid is True


def test_verification_detects_modified_metadata() -> None:
    session = _session()
    tenant = Tenant(slug="pilot", name="Pilot")
    session.add(tenant)
    session.flush()
    entry = append_audit_event(
        session,
        tenant_id=tenant.id,
        actor_user_id=None,
        event_type="auth.login_denied",
        target_type="identity",
        target_id=uuid4(),
        metadata={"reason": "membership_required"},
    )
    entry.metadata_json = {"reason": "substituted"}
    session.flush()

    result = verify_audit_chain(session, tenant_id=tenant.id)

    assert result.valid is False
    assert result.first_invalid_sequence == entry.sequence
