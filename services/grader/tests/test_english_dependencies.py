import math
import sys
from types import SimpleNamespace

import pytest

from edu_grader.english_dependencies import (
    EnglishDependencyError,
    LanguageToolClient,
    SentenceTransformerSimilarity,
    StaticSimilarity,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


def test_languagetool_maps_match_offsets_categories_and_replacements() -> None:
    captured: dict[str, object] = {}

    def post(url: str, *, data: dict[str, str], timeout: float) -> FakeResponse:
        captured.update(url=url, data=data, timeout=timeout)
        return FakeResponse(
            {
                "matches": [
                    {
                        "offset": 3,
                        "length": 2,
                        "rule": {
                            "id": "EN_A_VS_AN",
                            "issueType": "grammar",
                            "category": {"id": "GRAMMAR"},
                        },
                        "message": "Use an",
                        "replacements": [{"value": "an"}],
                    }
                ]
            }
        )

    client = LanguageToolClient("http://languagetool:8010/v2", timeout_seconds=1, post=post)

    matches = client.check("It a apple.")

    assert captured == {
        "url": "http://languagetool:8010/v2/check",
        "data": {"text": "It a apple.", "language": "en-US"},
        "timeout": 1,
    }
    assert matches[0].offset == 3
    assert matches[0].length == 2
    assert matches[0].rule_id == "EN_A_VS_AN"
    assert matches[0].category == "GRAMMAR"
    assert matches[0].issue_type == "grammar"
    assert matches[0].replacements == ["an"]


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -1.01, 1.01])
def test_similarity_rejects_non_cosine_scores(value: float) -> None:
    with pytest.raises(EnglishDependencyError, match="invalid similarity score"):
        StaticSimilarity(value).score("left", "right")


def test_static_similarity_accepts_negative_cosine_scores() -> None:
    similarity = StaticSimilarity(-0.2)

    assert similarity.score("query", "comparison") == -0.2
    assert similarity.score_many("query", ["first", "second"]) == [-0.2, -0.2]


def test_static_similarity_scores_each_comparison_in_order() -> None:
    similarity = StaticSimilarity(0.75)

    scores = similarity.score_many("query", ["first", "second"])

    assert scores == [0.75, 0.75]


def test_sentence_transformer_similarity_rejects_empty_embeddings(tmp_path, monkeypatch) -> None:
    (tmp_path / "metadata.json").write_text(
        '{"model_id":"test-model","revision":"test-revision","digest":"test-digest"}',
        encoding="utf-8",
    )

    class FakeSentenceTransformer:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def encode(self, texts: list[str], *, normalize_embeddings: bool) -> list[list[float]]:
            assert texts == ["query", "comparison"]
            assert normalize_embeddings is True
            return [[], []]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    similarity = SentenceTransformerSimilarity(
        tmp_path,
        model_id="test-model",
        revision="test-revision",
        digest="test-digest",
    )

    with pytest.raises(EnglishDependencyError, match="could not score"):
        similarity.score_many("query", ["comparison"])
