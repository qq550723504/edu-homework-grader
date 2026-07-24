from __future__ import annotations

from edu_grader_api.services.verification_capacity import (
    MAX_PROMPT_CHARS,
    VERIFICATION_CAPACITY_RULESET_VERSION,
    evaluate_verification_capacity,
)


def candidate(*, prompt: str) -> dict[str, object]:
    return {
        "objective_revision_id": "00000000-0000-0000-0000-000000000001",
        "question_type": "M1",
        "policy_version": "1",
        "prompt": prompt,
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the two whole numbers.",
        "knowledge_point": "whole-number addition",
        "difficulty": 0.2,
    }


def test_exact_prompt_limit_is_allowed() -> None:
    evaluation = evaluate_verification_capacity(candidate(prompt="x" * MAX_PROMPT_CHARS))

    assert "prompt_chars" not in evaluation.violations


def test_lone_unicode_surrogate_fails_closed_without_content() -> None:
    evaluation = evaluate_verification_capacity(candidate(prompt="\ud800"))

    assert evaluation.load_bucket == "invalid"
    assert evaluation.violations == ("candidate_invalid",)
    assert [finding.code for finding in evaluation.findings] == [
        "candidate_capacity_payload_invalid"
    ]
    assert evaluation.findings[0].evidence == {
        "ruleset_version": VERIFICATION_CAPACITY_RULESET_VERSION,
        "reason": "candidate_not_serializable",
    }
