from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.db import Base
from edu_grader_api.github_oidc import GitHubWorkflowIdentity
from edu_grader_api.services.operational_evaluation_runs import (
    OperationalEvaluationRunConflict,
    complete_run,
    create_run,
    purge_expired_runs,
)


NOW = datetime(2026, 7, 29, tzinfo=UTC)
IDENTITY = GitHubWorkflowIdentity(
    repository_id="123", owner_id="456", run_id="789", workflow_ref="workflow@main"
)
SPEC = {"spec_id": "operational-v1", "export": {"tenant_id": "tenant-1"}}
SIGNED_REPORT = {"promotion_eligible": False, "export_manifest": {"record_count": 0}}


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_same_github_run_and_spec_is_idempotent(session: Session) -> None:
    first = create_run(session, identity=IDENTITY, spec_json=SPEC, now=NOW)
    second = create_run(session, identity=IDENTITY, spec_json=SPEC, now=NOW)

    assert second.run.id == first.run.id
    assert second.callback_token is None
    assert first.run.callback_token_digest != first.callback_token


def test_same_github_run_rejects_a_different_spec(session: Session) -> None:
    create_run(session, identity=IDENTITY, spec_json=SPEC, now=NOW)

    with pytest.raises(OperationalEvaluationRunConflict):
        create_run(session, identity=IDENTITY, spec_json={"spec_id": "other"}, now=NOW)


def test_callback_persists_only_signed_report_and_expires_after_thirty_days(
    session: Session,
) -> None:
    created = create_run(session, identity=IDENTITY, spec_json=SPEC, now=NOW)

    completed = complete_run(
        session,
        run_id=created.run.id,
        callback_token=created.callback_token or "",
        report_json=SIGNED_REPORT,
        now=NOW,
    )

    assert completed.report_json == SIGNED_REPORT
    assert completed.expires_at == NOW + timedelta(days=30)
    assert completed.callback_token_digest is None
    assert purge_expired_runs(session, now=completed.expires_at) == [completed.id]


def test_callback_rejects_raw_evaluation_records(session: Session) -> None:
    created = create_run(session, identity=IDENTITY, spec_json=SPEC, now=NOW)

    with pytest.raises(ValueError, match="raw evaluation data"):
        complete_run(
            session,
            run_id=created.run.id,
            callback_token=created.callback_token or "",
            report_json={"records": [{"prompt": "private"}]},
            now=NOW,
        )
