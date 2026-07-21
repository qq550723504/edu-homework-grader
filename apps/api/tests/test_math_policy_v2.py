from __future__ import annotations

import pytest

from edu_grader_api.policies import validate_policy
from edu_grader_api.services.grader import HttpGraderClient, MathAnswerNormalizationError
from edu_grader_api.services.questions import _required_test_categories


class _Response:
    def __init__(self, payload: dict[str, object], *, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error

    def raise_for_status(self) -> None:
        if self._error is not None:
            raise self._error

    def json(self) -> dict[str, object]:
        return self._payload


def test_m2_v2_accepts_mathjson_and_m2_v1_remains_supported() -> None:
    assert validate_policy("M2", "2", {"expected": ["Add", 1, "x"], "variables": ["x"]}) == []
    assert validate_policy("M2", "1", {"expected": {"type": "symbol", "name": "x"}}) == []
    assert validate_policy("M2", "2", {"expected": {"type": "symbol", "name": "x"}})


def test_m2_v2_client_calls_v2_grader_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> _Response:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return _Response(
            {
                "decision": "auto_accepted",
                "score": 1,
                "criteria": [],
                "grader_version": "grader-0.1.0",
            }
        )

    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", fake_post)
    result = HttpGraderClient("http://grader").grade(
        "M2",
        {"expected": ["Add", 1, "x"], "variables": ["x"]},
        {"format": "mathjson-v1", "mathjson": ["Add", "x", 1]},
    )

    assert result.decision == "auto_accepted"
    assert captured == {
        "url": "http://grader/v1/grade/math/expression-v2",
        "json": {
            "student_mathjson": ["Add", "x", 1],
            "expected_mathjson": ["Add", 1, "x"],
            "variables": ["x"],
            "required_form": None,
            "form_score": 0,
            "max_score": 1,
        },
        "timeout": 10,
    }


def test_m2_v2_client_forwards_null_mathjson_to_grader(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, *, json: dict[str, object], timeout: int) -> _Response:
        captured.update({"url": url, "json": json, "timeout": timeout})
        return _Response(
            {
                "decision": "needs_review",
                "score": 0,
                "criteria": [],
                "grader_version": "grader-0.1.0",
            }
        )

    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", fake_post)
    result = HttpGraderClient("http://grader").grade(
        "M2",
        {"expected": ["Add", 1, "x"], "variables": ["x"]},
        {"mathjson": None},
        policy_version="2",
    )

    assert result.decision == "needs_review"
    assert captured["url"] == "http://grader/v1/grade/math/expression-v2"
    assert captured["json"] == {
        "student_mathjson": None,
        "expected_mathjson": ["Add", 1, "x"],
        "variables": ["x"],
        "required_form": None,
        "form_score": 0,
        "max_score": 1,
    }


def test_normalizer_maps_typed_grader_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    error = __import__("httpx").HTTPStatusError(
        "unprocessable",
        request=__import__("httpx").Request("POST", "http://grader/v1/normalize/mathjson"),
        response=__import__("httpx").Response(
            422,
            json={"code": "unsupported_operator", "message": "operator is not supported"},
        ),
    )
    monkeypatch.setattr(
        "edu_grader_api.services.grader.httpx.post",
        lambda *_, **__: _Response({}, error=error),
    )

    with pytest.raises(MathAnswerNormalizationError) as raised:
        HttpGraderClient("http://grader").normalize_math_answer({"mathjson": ["Assign", "x", 1]})

    assert raised.value.code == "unsupported_operator"


def test_m2_v2_requires_mathjson_specific_publish_categories() -> None:
    assert _required_test_categories("M2", "1") == {
        "correct",
        "incorrect",
        "empty",
        "boundary",
        "invalid_ast",
    }
    assert _required_test_categories("M2", "2") == {
        "correct",
        "incorrect",
        "empty",
        "boundary",
        "invalid_ast",
        "invalid_mathjson",
        "resource_limit",
    }
