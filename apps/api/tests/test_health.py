from fastapi.testclient import TestClient

from edu_grader_api.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "api"


def test_capabilities_include_english_and_mathematics() -> None:
    response = TestClient(app).get("/v1/meta/capabilities")

    assert response.status_code == 200
    assert set(response.json()["subjects"]) == {"english", "mathematics"}
