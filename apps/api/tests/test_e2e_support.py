from edu_grader_api.e2e_support import DeterministicM2Client


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
