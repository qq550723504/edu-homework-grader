from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from edu_grader_api.main import app
from edu_grader_api.services.generation_default_governance import GenerationDefaultGovernanceError


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "api"


def test_ready_reports_database_availability(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))
    monkeypatch.setattr("edu_grader_api.main.validate_active_default", lambda _session: object())

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ready",
        "generation_default": "ready",
    }


def test_ready_fails_closed_without_an_active_generation_default(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))

    def unconfigured(_session):
        raise GenerationDefaultGovernanceError("generation_default_not_configured")

    monkeypatch.setattr("edu_grader_api.main.validate_active_default", unconfigured)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "ready",
        "generation_default": "unconfigured",
    }


def test_ready_keeps_an_authorized_initialization_path_out_of_traffic(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))
    monkeypatch.setattr(
        "edu_grader_api.main.settings.generation_governance_admin_subjects", "bootstrap-admin"
    )

    def unconfigured(_session):
        raise GenerationDefaultGovernanceError("generation_default_not_configured")

    monkeypatch.setattr("edu_grader_api.main.validate_active_default", unconfigured)

    response = TestClient(app).get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "ready",
        "generation_default": "unconfigured",
    }


def test_ready_keeps_the_api_available_when_the_active_generation_default_is_paused(
    monkeypatch,
) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))

    def unavailable(_session):
        raise GenerationDefaultGovernanceError("default_component_not_active")

    monkeypatch.setattr("edu_grader_api.main.validate_active_default", unavailable)

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "database": "ready",
        "generation_default": "unavailable",
    }


def test_capabilities_include_english_and_mathematics() -> None:
    response = TestClient(app).get("/v1/meta/capabilities")

    assert response.status_code == 200
    assert set(response.json()["subjects"]) == {"english", "mathematics"}
