from __future__ import annotations

import pytest

from edu_grader_api.services import verification_capacity as capacity
from edu_grader_api.services.verification_capacity import (
    MAX_JSON_NODES,
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


def test_node_limit_short_circuits_json_sizing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    value = candidate(prompt="bounded traversal")
    value["extra_nodes"] = list(range(MAX_JSON_NODES + 100))

    def fail_if_sized(value: object, limit: int) -> int:
        raise AssertionError("structurally oversized payload must not be serialized")

    monkeypatch.setattr(capacity, "_bounded_json_size", fail_if_sized)

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.blocked is True
    assert evaluation.observations["json_nodes"] == MAX_JSON_NODES + 1
    assert evaluation.violations == ("json_nodes",)


def test_json_size_saturates_at_limit_without_full_materialization() -> None:
    assert capacity._bounded_json_size("x" * 10_000, 32) == 33


def test_non_string_nested_json_key_fails_closed() -> None:
    value = candidate(prompt="invalid JSON key")
    value["rule_json"] = {1: "not a JSON object key"}

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.load_bucket == "invalid"
    assert evaluation.findings[0].evidence["reason"] == "candidate_not_serializable"
