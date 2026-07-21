from dataclasses import dataclass
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from edu_grader_api.auth import VerifiedIdentity, get_token_verifier
from edu_grader_api.db import Base, get_session
from edu_grader_api.main import app
from edu_grader_api.models import QuestionTestCase, QuestionVersion, Role, Tenant, User
from edu_grader_api.routers import questions as questions_router
from edu_grader_api.settings import settings


ISSUER = "http://localhost:8080/realms/edu-grader"


@dataclass
class StaticVerifier:
    identity: VerifiedIdentity

    def verify(self, token: str) -> VerifiedIdentity:
        return self.identity


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(settings, "oidc_issuer", ISSUER)
    monkeypatch.setattr(settings, "oidc_tenant_slug", "pilot")
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def authorize(client: TestClient, user: User) -> dict[str, str]:
    client.app.dependency_overrides[get_token_verifier] = lambda: StaticVerifier(
        VerifiedIdentity(issuer=ISSUER, subject=user.oidc_subject or "", school_id=user.school_id)
    )
    return {"Authorization": "Bearer test-token"}


def test_teacher_can_create_a_tenant_scoped_question(client: TestClient, session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()

    response = client.post(
        "/v1/questions",
        headers=authorize(client, teacher),
        json={
            "title": "Addition",
            "prompt": "What is 2 + 3?",
            "question_type": "M1",
            "policy_version": "1",
            "rule": {"expected": 5},
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Addition"
    assert body["version_number"] == 1
    assert body["status"] == "draft"
    assert body["id"]

    version = session.scalar(select(QuestionVersion).where(QuestionVersion.id == UUID(body["id"])))
    assert version is not None
    publish_response = client.post(
        f"/v1/question-versions/{version.id}/publish",
        headers=authorize(client, teacher),
    )
    assert publish_response.status_code == 409


def test_teacher_previews_a_draft_test_answer_without_persisting_it(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()
    headers = authorize(client, teacher)
    created = client.post(
        "/v1/questions",
        headers=headers,
        json={
            "title": "Addition",
            "prompt": "What is 2 + 3?",
            "question_type": "M1",
            "policy_version": "1",
            "rule": {"expected": 5},
        },
    )

    class PreviewGrader:
        def __init__(self, _: str) -> None:
            pass

        def grade(self, *_: object, **__: object) -> object:
            from edu_grader_api.services.questions import GradeResult

            return GradeResult(
                decision="auto_accepted",
                score=1,
                evidence={"criterion": "numeric_value"},
                grader_version="preview@1",
            )

    monkeypatch.setattr(questions_router, "HttpGraderClient", PreviewGrader)
    response = client.post(
        f"/v1/question-versions/{created.json()['id']}/test-case-preview",
        headers=headers,
        json={"answer": {"format": "text-v1", "text": "5"}},
    )

    assert response.status_code == 200
    assert response.json() == {
        "decision": "auto_accepted",
        "score": 1,
        "evidence": {"criterion": "numeric_value"},
        "grader_version": "preview@1",
    }
    assert session.scalar(
        select(QuestionVersion).where(QuestionVersion.id == UUID(created.json()["id"]))
    )
    assert (
        session.scalars(
            select(QuestionTestCase).where(
                QuestionTestCase.question_version_id == UUID(created.json()["id"])
            )
        ).all()
        == []
    )


def test_teacher_receives_editable_english_test_case_templates(
    client: TestClient, session: Session
) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()
    headers = authorize(client, teacher)
    created = client.post(
        "/v1/questions",
        headers=headers,
        json={
            "title": "Vocabulary",
            "prompt": "Name the animal.",
            "question_type": "E1",
            "policy_version": "2",
            "rule": {
                "accepted_answers": ["cat"],
                "normalization": {
                    "unicode_form": "NFKC",
                    "collapse_whitespace": True,
                    "ignore_case": True,
                    "ignore_terminal_punctuation": True,
                },
                "max_score": 1,
            },
        },
    )

    response = client.get(
        f"/v1/question-versions/{created.json()['id']}/test-case-templates", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "templates": [
            {"category": "correct", "answer": {"format": "text-v1", "text": "cat"}},
            {"category": "incorrect", "answer": {"format": "text-v1", "text": "not cat"}},
            {"category": "empty", "answer": {"format": "text-v1", "text": ""}},
            {"category": "boundary", "answer": {"format": "text-v1", "text": " cat. "}},
        ]
    }


def test_teacher_lists_and_filters_question_versions(client: TestClient, session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()
    headers = authorize(client, teacher)
    created = client.post(
        "/v1/questions",
        headers=headers,
        json={
            "title": "Algebra addition",
            "prompt": "What is 2 + 3?",
            "question_type": "M1",
            "policy_version": "1",
            "rule": {"expected": 5},
        },
    )

    response = client.get(
        "/v1/questions?query=algebra&question_type=M1&status=draft", headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {
        "question_versions": [
            {
                "id": created.json()["id"],
                "question_id": response.json()["question_versions"][0]["question_id"],
                "title": "Algebra addition",
                "prompt": "What is 2 + 3?",
                "question_type": "M1",
                "policy_version": "1",
                "status": "draft",
                "max_score": 1,
            }
        ]
    }


def test_teacher_reads_question_policy_catalog(client: TestClient, session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()

    response = client.get("/v1/question-policy-catalog", headers=authorize(client, teacher))

    assert response.status_code == 200
    assert {"question_type": "E4", "policy_version": "2"} in response.json()["policies"]
    assert {"question_type": "E4", "policy_version": "1"} not in response.json()["policies"]


def test_teacher_cannot_create_a_new_e4_v1_question(client: TestClient, session: Session) -> None:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=ISSUER,
        oidc_subject="teacher",
        display_name="Teacher",
    )
    session.add_all([tenant, teacher])
    session.commit()

    response = client.post(
        "/v1/questions",
        headers=authorize(client, teacher),
        json={
            "title": "Legacy E4",
            "prompt": "Explain.",
            "question_type": "E4",
            "policy_version": "1",
            "rule": {"rubric": "Legacy rubric"},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["errors"] == [
        {"path": "/", "message": "policy E4@1 cannot be used for new questions"}
    ]
