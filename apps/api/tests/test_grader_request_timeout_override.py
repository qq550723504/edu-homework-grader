from __future__ import annotations

import math

import pytest

from edu_grader_api.services import grader as adapter
from edu_grader_api.services.grader import HttpGraderClient


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "decision": "auto_accepted",
            "score": 1,
            "grader_version": "test-v1",
        }


def test_http_grader_client_uses_explicit_request_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_post(
        _url: str,
        *,
        json: dict[str, object],
        timeout: float,
    ) -> _Response:
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(adapter.httpx, "post", fake_post)

    result = HttpGraderClient(
        "http://localhost:8010",
        request_timeout_seconds=0.25,
    ).grade(
        "M1",
        {"expected": 4, "tolerance": 0},
        {"format": "text-v1", "text": "4"},
        policy_version="1",
    )

    assert result.decision == "auto_accepted"
    assert captured == {"timeout": 0.25}


@pytest.mark.parametrize("value", [True, 0, -1, math.inf, -math.inf, math.nan, 61])
def test_http_grader_client_rejects_invalid_explicit_request_timeout(
    value: object,
) -> None:
    with pytest.raises(ValueError, match="grader request timeout"):
        HttpGraderClient("http://localhost:8010", request_timeout_seconds=value)  # type: ignore[arg-type]
