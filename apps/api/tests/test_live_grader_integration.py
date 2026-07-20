from __future__ import annotations

import os

import pytest

from edu_grader_api.services.grader import HttpGraderClient


pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_GRADER_INTEGRATION") != "1",
    reason="requires the Compose Grader service; set LIVE_GRADER_INTEGRATION=1",
)


def test_core_api_http_grader_adapter_uses_real_grader_for_m1_m2_e1_and_e4() -> None:
    """Exercise the production HTTP adapter without replacing ``HttpGraderClient``.

    This is intentionally separate from the browser fixture, whose deterministic
    in-process grader keeps UI acceptance tests self-contained.
    """

    client = HttpGraderClient(os.environ.get("GRADER_BASE_URL", "http://localhost:8010"))

    numeric = client.grade(
        "M1",
        {"expected": 5, "tolerance": 0},
        {"format": "text-v1", "text": "5"},
        policy_version="1",
    )
    assert numeric.decision == "auto_accepted"
    assert numeric.score == 1

    expression = client.grade(
        "M2",
        {"expected": ["Add", "x", 1], "variables": ["x"], "max_score": 4},
        {"format": "mathjson-v1", "mathjson": ["Add", "x", 1]},
        policy_version="2",
    )
    assert expression.decision == "auto_accepted"
    assert expression.score == 4

    exact_english = client.grade(
        "E1",
        {"accepted_answers": ["Hello"], "max_score": 2},
        {"format": "text-v1", "text": "hello"},
        policy_version="2",
    )
    assert exact_english.decision == "auto_accepted"
    assert exact_english.score == 2

    assisted_english = client.grade(
        "E4",
        {
            "scoring_points": [{"id": "evidence", "evidence_phrases": ["evidence"], "score": 3}],
            "max_score": 3,
        },
        {"format": "text-v1", "text": "This answer includes evidence."},
        policy_version="2",
    )
    assert assisted_english.decision == "needs_review"
    assert assisted_english.evidence["requires_review"] is True
