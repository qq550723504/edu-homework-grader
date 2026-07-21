from edu_grader_api.e2e_support import DeterministicE2EGraderClient, DeterministicM2Client


def test_e2e_grader_evaluates_m1_numeric_answers_against_the_rule() -> None:
    client = DeterministicM2Client("unused")

    accepted = client.grade(
        "M1", {"expected": 5}, {"format": "text-v1", "text": "5"}, policy_version="1"
    )
    rejected = client.grade(
        "M1", {"expected": 5}, {"format": "text-v1", "text": "4"}, policy_version="1"
    )

    assert (accepted.decision, accepted.score) == ("auto_accepted", 1.0)
    assert (rejected.decision, rejected.score) == ("auto_rejected", 0.0)


def test_e2e_grader_covers_english_authoring_policy_boundaries() -> None:
    client = DeterministicE2EGraderClient("unused")

    e1_accepted = client.grade(
        "E1",
        {"accepted_answers": ["cat"], "max_score": 1},
        {"format": "text-v1", "text": "cat"},
        policy_version="2",
    )
    e2_rejected = client.grade(
        "E2",
        {"accepted_forms": ["went"], "max_score": 1},
        {"format": "text-v1", "text": "go"},
        policy_version="1",
    )
    e3_review = client.grade(
        "E3",
        {"grammar_feedback_required": True, "max_score": 1},
        {"format": "text-v1", "text": "I go."},
        policy_version="1",
    )
    e4_review = client.grade(
        "E4",
        {"scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}]},
        {"format": "text-v1", "text": "The bridge closed."},
        policy_version="2",
    )

    assert (e1_accepted.decision, e1_accepted.score) == ("auto_accepted", 1.0)
    assert (e2_rejected.decision, e2_rejected.score) == ("auto_rejected", 0.0)
    assert (e3_review.decision, e3_review.score) == ("needs_review", 0.0)
    assert (e4_review.decision, e4_review.score) == ("needs_review", 0.0)
