import math

import pytest

from edu_grader.english_dependencies import (
    EnglishDependencyError,
    LanguageToolClient,
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


def test_similarity_rejects_non_finite_scores() -> None:
    with pytest.raises(EnglishDependencyError, match="invalid similarity score"):
        StaticSimilarity(math.nan).score("left", "right")


def test_static_similarity_scores_each_comparison_in_order() -> None:
    similarity = StaticSimilarity(0.75)

    scores = similarity.score_many("query", ["first", "second"])

    assert scores == [0.75, 0.75]
