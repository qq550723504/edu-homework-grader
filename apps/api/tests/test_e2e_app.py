from collections.abc import Iterator
from contextlib import contextmanager
import importlib
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jwt.exceptions import InvalidTokenError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import PyJWKTokenVerifier, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.e2e_support import STUDENT_TOKEN, TEACHER_TOKEN
from edu_grader_api.main import app as production_app


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextmanager
def e2e_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_path = tmp_path / "e2e.sqlite"
    monkeypatch.setenv(
        "E2E_DATABASE_URL",
        f"sqlite+pysqlite:///{database_path.as_posix()}",
    )
    e2e_app = importlib.import_module("edu_grader_api.e2e_app")
    with TestClient(e2e_app.app) as client:
        yield client


def test_e2e_app_accepts_only_its_static_fictional_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with e2e_client(tmp_path, monkeypatch) as client:
        student = client.get("/v1/me", headers=bearer(STUDENT_TOKEN))
        teacher = client.get("/v1/me", headers=bearer(TEACHER_TOKEN))
        assignments = client.get("/v1/student/assignments", headers=bearer(STUDENT_TOKEN))

        assert student.status_code == 200
        assert student.json()["role"] == "student"
        assert teacher.status_code == 200
        assert teacher.json()["role"] == "teacher"
        assert client.get("/v1/me", headers=bearer("production-token")).status_code == 401
        assert assignments.status_code == 200
        assert [item["title"] for item in assignments.json()["pending"]] == [
            "Expression equivalence"
        ]
        assignment_id = assignments.json()["pending"][0]["id"]
        detail = client.get(
            f"/v1/student/assignments/{assignment_id}",
            headers=bearer(STUDENT_TOKEN),
        )
        assert detail.status_code == 200
        attempt_id = detail.json()["attempt"]["id"]
        item_id = detail.json()["items"][0]["id"]
        saved = client.put(
            f"/v1/student/attempts/{attempt_id}/answers/{item_id}",
            headers=bearer(STUDENT_TOKEN),
            json={
                "answer": {
                    "format": "mathjson-v1",
                    "latex": "x+1",
                    "mathjson": ["Add", "x", 1],
                },
                "version": 0,
            },
        )
        submitted = client.post(
            f"/v1/student/assignments/{assignment_id}/submit",
            headers=bearer(STUDENT_TOKEN) | {"Idempotency-Key": str(uuid4())},
        )
        assert saved.status_code == 200
        assert submitted.status_code == 200


def test_production_app_does_not_accept_e2e_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    def reject_token(_self: PyJWKTokenVerifier, _token: str) -> None:
        raise InvalidTokenError("not a production token")

    monkeypatch.setattr(PyJWKTokenVerifier, "verify", reject_token)
    assert get_token_verifier not in production_app.dependency_overrides
    production_app.dependency_overrides[get_session] = lambda: session
    try:
        with TestClient(production_app) as client:
            response = client.get("/v1/me", headers=bearer(STUDENT_TOKEN))
    finally:
        production_app.dependency_overrides.clear()
        session.close()
        engine.dispose()

    assert response.status_code == 401
