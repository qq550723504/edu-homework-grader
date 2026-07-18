from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import edu_grader_api.services.assignments as assignments
from edu_grader_api.models import GradingPolicy
from edu_grader_api.services.grader import MathAnswerNormalizationError
from test_assignments import authorize, published_assignment_for_student
from test_assignments import client as _client_fixture  # noqa: F401
from test_assignments import session as _session_fixture  # noqa: F401

client = _client_fixture
session = _session_fixture


class FakeNormalizerClient:
    def __init__(self, _: str) -> None:
        self.calls: list[dict[str, object]] = []

    def normalize_math_answer(self, answer: dict[str, object]) -> dict[str, object]:
        self.calls.append(answer)
        if answer["mathjson"] == ["Assign", "x", 1]:
            raise MathAnswerNormalizationError("unsupported_operator", "operator is not supported")
        return {
            "type": "add",
            "args": [{"type": "symbol", "name": "x"}, {"type": "number", "value": "1"}],
        }


def _make_mathjson_item(session) -> tuple[object, object, object, object, object]:
    student, classroom, assignment, item, version = published_assignment_for_student(session)
    policy = GradingPolicy(question_type="M2", policy_version="2", json_schema={})
    version.question_type = "M2"
    version.grading_policy = policy
    version.rule_json = {
        "expected": ["Add", 1, "x"],
        "variables": ["x"],
        "required_form": "expanded",
    }
    session.add(policy)
    session.commit()
    return student, classroom, assignment, item, version


def test_m2_v2_detail_redacts_expected_and_save_persists_server_ast(
    client: TestClient, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    student, _, assignment, item, _ = _make_mathjson_item(session)
    monkeypatch.setattr(assignments, "HttpGraderClient", FakeNormalizerClient, raising=False)

    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )
    attempt_id = detail.json()["attempt"]["id"]
    saved = client.put(
        f"/v1/student/attempts/{attempt_id}/answers/{item.id}",
        headers=authorize(client, student),
        json={
            "answer": {
                "format": "mathjson-v1",
                "latex": "x+1",
                "mathjson": ["Add", "x", 1],
            },
            "version": 0,
        },
    )

    assert detail.json()["items"][0]["input"] == {
        "kind": "mathjson-v1",
        "variables": ["x"],
        "required_form": "expanded",
    }
    assert "expected" not in detail.json()["items"][0]
    assert saved.status_code == 200
    assert saved.json()["answer"] == {
        "format": "mathjson-v1",
        "latex": "x+1",
        "mathjson": ["Add", "x", 1],
        "ast": {
            "type": "add",
            "args": [
                {"type": "symbol", "name": "x"},
                {"type": "number", "value": "1"},
            ],
        },
    }


def test_m2_v2_rejects_unsafe_mathjson_with_typed_error(
    client: TestClient, session, monkeypatch: pytest.MonkeyPatch
) -> None:
    student, _, assignment, item, _ = _make_mathjson_item(session)
    monkeypatch.setattr(assignments, "HttpGraderClient", FakeNormalizerClient, raising=False)
    detail = client.get(
        f"/v1/student/assignments/{assignment.id}", headers=authorize(client, student)
    )

    response = client.put(
        f"/v1/student/attempts/{detail.json()['attempt']['id']}/answers/{item.id}",
        headers=authorize(client, student),
        json={
            "answer": {
                "format": "mathjson-v1",
                "latex": "x:=1",
                "mathjson": ["Assign", "x", 1],
            },
            "version": 0,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_operator"
