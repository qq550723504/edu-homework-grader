from __future__ import annotations

import json

import pytest

from edu_grader_api.services.verification_capacity import (
    MAX_ASSERTIONS_BYTES,
    MAX_CANDIDATE_BYTES,
    MAX_COMBINING_MARK_RUN,
    MAX_EVIDENCE_PHRASES,
    MAX_EVIDENCE_PHRASE_CHARS,
    MAX_EXPLANATION_CHARS,
    MAX_JSON_DEPTH,
    MAX_JSON_NODES,
    MAX_PROMPT_CHARS,
    MAX_READING_MATERIAL_CHARS,
    MAX_RULE_JSON_BYTES,
    VERIFICATION_CAPACITY_RULESET_VERSION,
    evaluate_verification_capacity,
)


def candidate(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "objective_revision_id": "00000000-0000-0000-0000-000000000001",
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "What is 2 + 2?",
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the two whole numbers.",
        "knowledge_point": "whole-number addition",
        "difficulty": 0.2,
        "verification_assertions": {
            "final_answer_text": "4",
            "final_answer_mathjson": None,
            "declared_max_score": 1,
        },
        "reading_material": None,
    }
    value.update(overrides)
    return value


def finding_codes(value: dict[str, object]) -> set[str]:
    evaluation = evaluate_verification_capacity(value)
    return {finding.code for finding in evaluation.findings}


def test_small_candidate_has_deidentified_capacity_signal() -> None:
    value = candidate()

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.blocked is False
    assert evaluation.load_bucket == "small"
    assert evaluation.violations == ()
    signal = evaluation.feature_summary()
    assert signal["version"] == VERIFICATION_CAPACITY_RULESET_VERSION
    assert signal["load_bucket"] == "small"
    persisted = json.dumps(signal)
    assert "What is 2 + 2?" not in persisted
    assert "whole-number addition" not in persisted
    assert "final_answer_text" not in persisted


@pytest.mark.parametrize(
    "field,limit,metric",
    [
        ("prompt", MAX_PROMPT_CHARS, "prompt_chars"),
        ("explanation", MAX_EXPLANATION_CHARS, "explanation_chars"),
        ("reading_material", MAX_READING_MATERIAL_CHARS, "reading_material_chars"),
    ],
)
def test_text_limits_block_without_persisting_text(field: str, limit: int, metric: str) -> None:
    secret = "S" * (limit + 1)
    value = candidate(**{field: secret})

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.blocked is True
    assert metric in evaluation.violations
    finding = evaluation.findings[0]
    assert finding.code == "candidate_capacity_limit_exceeded"
    assert metric in finding.evidence["violations"]
    assert secret not in json.dumps(finding.evidence)


def test_total_candidate_bytes_are_bounded() -> None:
    value = candidate(extra_payload="x" * MAX_CANDIDATE_BYTES)

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.load_bucket == "oversize"
    assert "candidate_bytes" in evaluation.violations


def test_rule_and_assertion_bytes_are_bounded_independently() -> None:
    rule_evaluation = evaluate_verification_capacity(
        candidate(rule_json={"expected": 4, "padding": "x" * MAX_RULE_JSON_BYTES})
    )
    assertion_evaluation = evaluate_verification_capacity(
        candidate(
            verification_assertions={
                "final_answer_text": "x" * MAX_ASSERTIONS_BYTES,
                "final_answer_mathjson": None,
                "declared_max_score": 1,
            }
        )
    )

    assert "rule_json_bytes" in rule_evaluation.violations
    assert "verification_assertions_bytes" in assertion_evaluation.violations


def test_json_depth_limit_is_deterministic() -> None:
    nested: object = "leaf"
    for _ in range(MAX_JSON_DEPTH + 2):
        nested = [nested]

    evaluation = evaluate_verification_capacity(candidate(rule_json={"expected": nested}))

    assert "json_depth" in evaluation.violations
    assert evaluation.observations["json_depth"] > MAX_JSON_DEPTH


def test_json_node_limit_stops_large_structures() -> None:
    value = candidate(extra_nodes=list(range(MAX_JSON_NODES + 100)))

    evaluation = evaluate_verification_capacity(value)

    assert "json_nodes" in evaluation.violations
    assert evaluation.observations["json_nodes"] == MAX_JSON_NODES + 1


def test_rubric_count_and_phrase_limits_are_bounded() -> None:
    too_many_phrases = ["evidence"] * (MAX_EVIDENCE_PHRASES + 1)
    scoring_points = [
        {
            "id": "point",
            "score": 1,
            "evidence_phrases": too_many_phrases,
        }
    ]

    evaluation = evaluate_verification_capacity(
        candidate(question_type="E4", rule_json={"scoring_points": scoring_points})
    )

    assert "evidence_phrases" in evaluation.violations


def test_single_evidence_phrase_length_is_bounded() -> None:
    phrase = "e" * (MAX_EVIDENCE_PHRASE_CHARS + 1)
    evaluation = evaluate_verification_capacity(
        candidate(
            question_type="E4",
            rule_json={
                "scoring_points": [{"id": "point", "score": 1, "evidence_phrases": [phrase]}]
            },
        )
    )

    assert "evidence_phrase_chars" in evaluation.violations
    assert phrase not in json.dumps(evaluation.feature_summary())


def test_control_characters_are_blocked_but_normal_whitespace_is_allowed() -> None:
    blocked = evaluate_verification_capacity(candidate(prompt="safe\u0000unsafe"))
    allowed = evaluate_verification_capacity(candidate(prompt="line one\nline two\tvalue"))

    assert "control_characters" in blocked.violations
    assert "control_characters" not in allowed.violations


def test_pathological_combining_mark_run_is_blocked() -> None:
    prompt = "a" + "\u0301" * (MAX_COMBINING_MARK_RUN + 1)

    evaluation = evaluate_verification_capacity(candidate(prompt=prompt))

    assert "combining_mark_run" in evaluation.violations
    assert prompt not in json.dumps(evaluation.findings[0].evidence)


def test_non_serializable_candidate_fails_closed() -> None:
    value = candidate(extra={1, 2, 3})

    evaluation = evaluate_verification_capacity(value)

    assert evaluation.load_bucket == "invalid"
    assert evaluation.violations == ("candidate_invalid",)
    assert [finding.code for finding in evaluation.findings] == [
        "candidate_capacity_payload_invalid"
    ]
    assert evaluation.findings[0].evidence == {
        "ruleset_version": VERIFICATION_CAPACITY_RULESET_VERSION,
        "reason": "candidate_not_serializable",
    }


def test_non_object_candidate_fails_closed() -> None:
    evaluation = evaluate_verification_capacity(["not", "an", "object"])

    assert evaluation.load_bucket == "invalid"
    assert evaluation.findings[0].evidence["reason"] == "candidate_not_object"


def test_capacity_finding_contains_only_violating_metrics() -> None:
    evaluation = evaluate_verification_capacity(candidate(prompt="x" * (MAX_PROMPT_CHARS + 1)))

    evidence = evaluation.findings[0].evidence
    assert evidence["violations"] == ["prompt_chars"]
    assert set(evidence["observations"]) == {"prompt_chars"}
    assert set(evidence["limits"]) == {"prompt_chars"}
