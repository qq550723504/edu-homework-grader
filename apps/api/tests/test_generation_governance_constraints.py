from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    GenerationControlState,
    GenerationGovernanceEntry,
    GenerationGovernanceTargetType,
    Tenant,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def tenant(session: Session, slug: str = "pilot") -> Tenant:
    item = Tenant(slug=slug, name=slug.title())
    session.add(item)
    session.flush()
    return item


def entry(
    *,
    tenant_id,
    is_global: bool,
    target_key: str = "generator-v2",
) -> GenerationGovernanceEntry:
    return GenerationGovernanceEntry(
        tenant_id=tenant_id,
        is_global=is_global,
        target_type=GenerationGovernanceTargetType.PROMPT_VERSION,
        target_key=target_key,
        control_state=GenerationControlState.ACTIVE,
    )


def test_database_rejects_global_scope_with_tenant_id(session: Session) -> None:
    item = tenant(session)
    session.add(entry(tenant_id=item.id, is_global=True))

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_duplicate_global_target(session: Session) -> None:
    session.add_all(
        [
            entry(tenant_id=None, is_global=True),
            entry(tenant_id=None, is_global=True),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_duplicate_target_within_tenant(session: Session) -> None:
    item = tenant(session)
    session.add_all(
        [
            entry(tenant_id=item.id, is_global=False),
            entry(tenant_id=item.id, is_global=False),
        ]
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_database_allows_same_target_for_different_tenants(session: Session) -> None:
    first = tenant(session, "first")
    second = tenant(session, "second")
    session.add_all(
        [
            entry(tenant_id=first.id, is_global=False),
            entry(tenant_id=second.id, is_global=False),
        ]
    )
    session.commit()


def test_database_rejects_tenant_scope_without_tenant_id(session: Session) -> None:
    session.add(entry(tenant_id=None, is_global=False, target_key=str(uuid4())))

    with pytest.raises(IntegrityError):
        session.commit()
