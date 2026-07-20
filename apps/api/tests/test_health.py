from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from edu_grader_api.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "api"


def test_ready_reports_database_availability(monkeypatch) -> None:
    monkeypatch.setattr("edu_grader_api.main.engine", create_engine("sqlite+pysqlite:///:memory:"))

    response = TestClient(app).get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ready"}


def test_capabilities_include_english_and_mathematics() -> None:
    response = TestClient(app).get("/v1/meta/capabilities")

    assert response.status_code == 200
    assert set(response.json()["subjects"]) == {"english", "mathematics"}
