from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.db import Base, get_session
from edu_grader_api.github_oidc import GitHubWorkflowIdentity
from edu_grader_api.main import app
from edu_grader_api.routers.operational_evaluations import (
    get_github_oidc_verifier,
    get_operational_evaluation_job_launcher,
)
from edu_grader_api.services.operational_evaluation_kubernetes import (
    KubernetesOperationalEvaluationJobLauncher,
)

IDENTITY = GitHubWorkflowIdentity(
    repository_id="123", owner_id="456", run_id="789", workflow_ref="workflow@main"
)
SPEC = {"spec_id": "operational-v1", "export": {"tenant_id": "tenant-1"}}


@dataclass
class StaticGitHubVerifier:
    identity: GitHubWorkflowIdentity

    def verify(self, _token: str) -> GitHubWorkflowIdentity:
        return self.identity


@dataclass
class FakeJobLauncher:
    launches: list[tuple[str, str]] = field(default_factory=list)
    deleted_callback_runs: list[str] = field(default_factory=list)

    def launch(self, *, run_id: str, spec_json: dict[str, object], callback_token: str) -> None:
        self.launches.append((run_id, callback_token))

    def delete_callback_secret(self, *, run_id: str) -> None:
        self.deleted_callback_runs.append(run_id)


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


@pytest.fixture
def client(session: Session) -> tuple[TestClient, FakeJobLauncher]:
    launcher = FakeJobLauncher()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_github_oidc_verifier] = lambda: StaticGitHubVerifier(IDENTITY)
    app.dependency_overrides[get_operational_evaluation_job_launcher] = lambda: launcher
    with TestClient(app) as client:
        yield client, launcher
    app.dependency_overrides.clear()


def headers() -> dict[str, str]:
    return {"Authorization": "Bearer github-oidc-token"}


def test_valid_github_oidc_request_creates_exactly_one_job(
    client: tuple[TestClient, FakeJobLauncher],
) -> None:
    http, launcher = client

    first = http.post(
        "/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=headers()
    )
    second = http.post(
        "/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=headers()
    )

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert len(launcher.launches) == 1


def test_report_endpoint_returns_only_completed_signed_report(
    client: tuple[TestClient, FakeJobLauncher],
) -> None:
    http, launcher = client
    created = http.post(
        "/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=headers()
    )
    run_id = created.json()["id"]
    callback_token = launcher.launches[0][1]

    completed = http.post(
        f"/v1/internal/operational-evaluations/{run_id}/completion",
        json={"report": {"promotion_eligible": False, "export_manifest": {"record_count": 0}}},
        headers={"X-Operational-Evaluation-Callback": callback_token},
    )
    report = http.get(f"/v1/internal/operational-evaluations/{run_id}/report", headers=headers())

    assert completed.status_code == 204
    assert launcher.deleted_callback_runs == [run_id]
    assert report.status_code == 200
    assert report.json()["promotion_eligible"] is False
    assert "records" not in report.text


def test_report_endpoint_rejects_incomplete_run(client: tuple[TestClient, FakeJobLauncher]) -> None:
    http, _launcher = client
    created = http.post(
        "/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=headers()
    )

    response = http.get(
        f"/v1/internal/operational-evaluations/{created.json()['id']}/report", headers=headers()
    )

    assert response.status_code == 409


def test_executor_failure_marks_run_failed(client: tuple[TestClient, FakeJobLauncher]) -> None:
    http, launcher = client
    created = http.post(
        "/v1/internal/operational-evaluations", json={"spec": SPEC}, headers=headers()
    )
    run_id = created.json()["id"]

    completed = http.post(
        f"/v1/internal/operational-evaluations/{run_id}/completion",
        json={"failure_code": "evaluation_execution_failed"},
        headers={"X-Operational-Evaluation-Callback": launcher.launches[0][1]},
    )
    status = http.get(f"/v1/internal/operational-evaluations/{run_id}", headers=headers())

    assert completed.status_code == 204
    assert launcher.deleted_callback_runs == [run_id]
    assert status.json()["status"] == "failed"


def test_launcher_uses_pinned_image_and_never_mounts_application_runtime_secret() -> None:
    launcher = KubernetesOperationalEvaluationJobLauncher(
        namespace="edu-homework-grader",
        image="ghcr.io/qq550723504/edu-homework-grader-api@sha256:" + "a" * 64,
        runtime_secret_name="operational-evaluation-runtime",
        callback_base_url="http://api:8000",
        batch_api=object(),
        core_api=object(),
    )

    manifest = launcher.manifest_for(
        run_id="run-1", spec_json=SPEC, callback_secret_name="callback-1"
    )
    serialized = str(manifest)
    container = manifest["spec"]["template"]["spec"]["containers"][0]

    assert container["image"].endswith("@sha256:" + "a" * 64)
    assert "edu-grader-runtime" not in serialized
    assert "operational-evaluation-runtime" in serialized
    assert manifest["spec"]["backoffLimit"] == 0
    assert manifest["spec"]["activeDeadlineSeconds"] == 900
