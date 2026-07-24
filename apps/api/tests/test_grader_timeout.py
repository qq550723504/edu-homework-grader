from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from edu_grader_api.services.grader import (
    GraderRequestTimeoutError,
    HttpGraderClient,
)
from edu_grader_api.settings import settings


def test_http_grader_uses_configured_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def fake_post(
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> httpx.Response:
        observed.update(url=url, json=json, timeout=timeout)
        return httpx.Response(
            200,
            json={
                "decision": "auto_accepted",
                "score": 1,
                "grader_version": "test-grader-v1",
            },
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(settings, "grader_request_timeout_seconds", 1.25)
    monkeypatch.setattr(httpx, "post", fake_post)

    result = HttpGraderClient("http://localhost:8010").grade(
        "M1",
        {"expected": 4, "tolerance": 0},
        {"format": "text-v1", "text": "4"},
        policy_version="1",
    )

    assert result.decision == "auto_accepted"
    assert observed["timeout"] == 1.25
    assert str(observed["url"]).endswith("/v1/grade/math/numeric")


@pytest.mark.parametrize(
    "operation,invoke",
    [
        (
            "grade",
            lambda client: client.grade(
                "M1",
                {"expected": 4, "tolerance": 0},
                {"format": "text-v1", "text": "4"},
                policy_version="1",
            ),
        ),
        (
            "normalizer",
            lambda client: client.normalize_math_answer(
                {"mathjson": ["Add", "x", 1], "variables": ["x"]}
            ),
        ),
        (
            "similarity",
            lambda client: client.semantic_similarity("prompt", ["comparison"]),
        ),
    ],
)
def test_http_grader_timeout_has_stable_operation_without_payload(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    invoke: Callable[[HttpGraderClient], object],
) -> None:
    def timeout_post(
        url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> httpx.Response:
        raise httpx.ReadTimeout(
            "internal URL and payload diagnostic",
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", timeout_post)
    client = HttpGraderClient("http://localhost:8010")

    with pytest.raises(GraderRequestTimeoutError) as raised:
        invoke(client)

    assert raised.value.operation == operation
    assert operation in str(raised.value)
    assert "localhost" not in str(raised.value)
    assert "payload" not in str(raised.value)
