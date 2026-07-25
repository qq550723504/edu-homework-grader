from __future__ import annotations

import pytest

from edu_grader.english_dependencies import StaticSimilarity
from edu_grader.main import SemanticSimilarityRequest, app, semantic_similarity


@pytest.mark.parametrize(
    ("cosine_score", "duplicate_score"),
    [
        (-1.0, 0.0),
        (-0.2, 0.0),
        (0.0, 0.0),
        (0.75, 0.75),
        (1.0, 1.0),
    ],
)
def test_semantic_similarity_route_maps_cosine_to_duplicate_score(
    monkeypatch: pytest.MonkeyPatch,
    cosine_score: float,
    duplicate_score: float,
) -> None:
    monkeypatch.setattr(
        app.state,
        "semantic_similarity",
        StaticSimilarity(cosine_score),
        raising=False,
    )
    monkeypatch.setattr(
        app.state,
        "embedding_dependency_version",
        {
            "id": "test-model",
            "revision": "test-revision",
            "digest": "sha256:test",
        },
        raising=False,
    )

    response = semantic_similarity(
        SemanticSimilarityRequest(
            query="Synthetic comparison query.",
            comparisons=["Synthetic comparison peer."],
        )
    )

    assert response.scores == [duplicate_score]
