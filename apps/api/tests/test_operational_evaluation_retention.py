from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.db import Base
from edu_grader_api.github_oidc import GitHubWorkflowIdentity
from edu_grader_api.services.operational_evaluation_retention import purge_expired_evaluations
from edu_grader_api.services.operational_evaluation_runs import complete_run, create_run


def test_retention_deletes_only_expired_callback_secrets() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine)
    deleted: list[str] = []
    identity = GitHubWorkflowIdentity("123", "456", "789", "workflow@main")
    now = datetime(2026, 7, 29, tzinfo=UTC)
    with Session(engine) as session:
        created = create_run(session, identity=identity, spec_json={"spec_id": "v1"}, now=now)
        completed = complete_run(
            session,
            run_id=created.run.id,
            callback_token=created.callback_token or "",
            report_json={"promotion_eligible": False},
            now=now,
        )
        purged = purge_expired_evaluations(
            session,
            now=completed.expires_at or now,
            delete_secret=deleted.append,
        )

    assert purged == [completed.id]
    assert deleted == [f"operational-evaluation-callback-{completed.id}"]
