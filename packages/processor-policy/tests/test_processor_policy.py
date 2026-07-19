import pytest

from edu_grader_processor_policy import (
    ProcessorPolicyError,
    assert_allowed_processor_url,
    assert_deidentified_payload,
)


def test_rejects_processor_host_not_in_allowlist() -> None:
    with pytest.raises(ProcessorPolicyError, match="not allowlisted"):
        assert_allowed_processor_url("https://model.example/check", frozenset({"languagetool"}))


def test_rejects_identity_field_in_nested_payload() -> None:
    with pytest.raises(ProcessorPolicyError, match="student_id"):
        assert_deidentified_payload({"answer": {"text": "x", "student_id": "forbidden"}})


def test_allows_a_minimal_grading_payload() -> None:
    assert_deidentified_payload(
        {
            "question_type": "E3",
            "policy_version": "1",
            "rule": {"max_score": 1},
            "answer": {"answer": "student response"},
        }
    )
