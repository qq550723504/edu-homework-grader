import math

import pytest
from edu_grader_processor_policy import ProcessorPolicyError

from edu_grader_api.services.grader import (
    EmbeddingDependencyVersion,
    HttpGraderClient,
    SemanticSimilarityResult,
)


EMBEDDING = {"id": "local-model", "revision": "test-revision", "digest": "sha256:test"}


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self._payload


def test_e4_request_preserves_policy_version_feedback_and_signals(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse(
            {
                "decision": "needs_review",
                "score": 0,
                "max_score": 1,
                "confidence": 0.8,
                "criteria": [],
                "feedback": [{"type": "grammar", "message": "Use an"}],
                "signals": [{"kind": "scoring_point", "highest_similarity": 0.95}],
                "requires_review": True,
                "grader_version": "grader-english-1",
            }
        )

    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", post)

    result = HttpGraderClient("http://grader").grade(
        "E4",
        {
            "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
            "max_score": 1,
        },
        {"format": "text-v1", "text": "road closed"},
        policy_version="2",
    )

    assert captured == {
        "url": "http://grader/v1/grade/english",
        "json": {
            "question_type": "E4",
            "policy_version": "2",
            "rule": {
                "scoring_points": [
                    {"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}
                ],
                "max_score": 1,
            },
            "answer": {"answer": "road closed"},
        },
        "timeout": 10,
    }
    assert result.evidence["feedback"] == [{"type": "grammar", "message": "Use an"}]
    assert result.evidence["signals"] == [{"kind": "scoring_point", "highest_similarity": 0.95}]
    assert result.evidence["requires_review"] is True


def test_http_grader_client_posts_semantic_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def post(url: str, *, json: dict[str, object], timeout: float) -> FakeResponse:
        captured.update(url=url, json=json, timeout=timeout)
        return FakeResponse({"scores": [0.94, 0.03], "embedding": EMBEDDING})

    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", post)

    result = HttpGraderClient("http://grader").semantic_similarity("query", ["first", "second"])

    assert result == SemanticSimilarityResult(
        scores=[0.94, 0.03],
        embedding=EmbeddingDependencyVersion(**EMBEDDING),
    )
    assert captured == {
        "url": "http://grader/v1/semantic-similarity",
        "json": {"query": "query", "comparisons": ["first", "second"]},
        "timeout": 10,
    }


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"scores": "not-a-list", "embedding": EMBEDDING},
        {"scores": [0.5], "embedding": EMBEDDING},
        {"scores": [True, 0.5], "embedding": EMBEDDING},
        {"scores": [math.nan, 0.5], "embedding": EMBEDDING},
        {"scores": [math.inf, 0.5], "embedding": EMBEDDING},
        {"scores": [-0.01, 0.5], "embedding": EMBEDDING},
        {"scores": [1.01, 0.5], "embedding": EMBEDDING},
    ],
)
def test_http_grader_client_rejects_malformed_semantic_scores(
    monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    monkeypatch.setattr(
        "edu_grader_api.services.grader.httpx.post", lambda *args, **kwargs: FakeResponse(payload)
    )

    with pytest.raises(ValueError, match="semantic similarity response is invalid"):
        HttpGraderClient("http://grader").semantic_similarity("query", ["first", "second"])


@pytest.mark.parametrize(
    "embedding",
    [
        None,
        {},
        {"id": "", "revision": "revision", "digest": "sha256:test"},
        {"id": "local-model", "revision": 1, "digest": "sha256:test"},
        {"id": "local-model", "revision": "revision", "digest": ""},
        {"id": "local-model", "revision": "revision"},
    ],
)
def test_http_grader_client_rejects_invalid_semantic_embedding_metadata(
    monkeypatch: pytest.MonkeyPatch, embedding: object
) -> None:
    monkeypatch.setattr(
        "edu_grader_api.services.grader.httpx.post",
        lambda *args, **kwargs: FakeResponse({"scores": [0.5], "embedding": embedding}),
    )

    with pytest.raises(ValueError, match="semantic similarity response is invalid"):
        HttpGraderClient("http://grader").semantic_similarity("query", ["comparison"])


def test_http_grader_client_validates_processor_policy_before_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted = False

    def post(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal posted
        posted = True
        return FakeResponse({"scores": [0.1]})

    monkeypatch.setattr("edu_grader_api.services.grader.httpx.post", post)

    with pytest.raises(ProcessorPolicyError, match="not allowlisted"):
        HttpGraderClient("https://external.example").semantic_similarity("query", ["comparison"])

    assert posted is False
