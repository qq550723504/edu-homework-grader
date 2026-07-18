from edu_grader_api.services.grader import HttpGraderClient


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
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
        {"answer": "road closed"},
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
