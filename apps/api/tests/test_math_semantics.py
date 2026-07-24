from __future__ import annotations

import json

import pytest

from edu_grader_api.services.math_semantics import (
    MATH_SEMANTICS_RULESET_VERSION,
    evaluate_math_semantics,
)


def test_m1_single_finite_numeric_value_is_supported() -> None:
    evaluation = evaluate_math_semantics(
        question_type="M1",
        policy_version="1",
        rule_json={"expected": 4, "tolerance": 0},
    )

    assert evaluation.support_status == "supported"
    assert evaluation.semantic_class == "single_numeric_value"
    assert evaluation.findings == ()
    assert evaluation.feature_summary() == {
        "availability": "available",
        "version": MATH_SEMANTICS_RULESET_VERSION,
        "question_type": "M1",
        "policy_version": "1",
        "support_status": "supported",
        "semantic_class": "single_numeric_value",
        "trigger_operator": None,
    }


@pytest.mark.parametrize(
    "expected,trigger",
    [
        ([1, 2], "list"),
        ((1, 2), "tuple"),
        ({1, 2}, "set"),
    ],
)
def test_m1_multiple_solution_containers_are_blocked(expected: object, trigger: str) -> None:
    evaluation = evaluate_math_semantics(
        question_type="M1", policy_version="1", rule_json={"expected": expected}
    )

    assert evaluation.support_status == "blocked"
    assert evaluation.semantic_class == "multiple_solution_set"
    assert evaluation.trigger_operator == trigger
    assert [finding.code for finding in evaluation.findings] == [
        "m1_multiple_solution_semantics_unsupported"
    ]


def test_m2_supported_expression_equivalence_has_no_findings() -> None:
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={
            "expected": ["Add", "x", ["Multiply", 2, "x"]],
            "variables": ["x"],
        },
    )

    assert evaluation.support_status == "supported"
    assert evaluation.semantic_class == "expression_equivalence"
    assert evaluation.findings == ()


@pytest.mark.parametrize(
    "expected,semantic_class,code,operator",
    [
        (
            ["Equal", "x", 2],
            "equation_or_inequality",
            "m2_equation_semantics_unsupported",
            "Equal",
        ),
        (
            ["Set", 1, 2],
            "multiple_solution_set",
            "m2_solution_set_semantics_unsupported",
            "Set",
        ),
        (
            ["Interval", 0, 1],
            "domain_restriction",
            "m2_domain_semantics_unsupported",
            "Interval",
        ),
        (
            ["Root", "x", 2],
            "extraneous_or_missing_root_risk",
            "m2_root_semantics_unsupported",
            "Root",
        ),
        (
            ["MissingCondition", "x"],
            "insufficient_conditions",
            "m2_insufficient_conditions_unsupported",
            "MissingCondition",
        ),
    ],
)
def test_m2_explicit_unsupported_semantics_have_dedicated_findings(
    expected: object, semantic_class: str, code: str, operator: str
) -> None:
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={"expected": expected, "variables": ["x"]},
    )

    assert evaluation.support_status == "blocked"
    assert evaluation.semantic_class == semantic_class
    assert evaluation.trigger_operator == operator
    assert [finding.code for finding in evaluation.findings] == [code]
    assert evaluation.findings[0].evidence == {
        "ruleset_version": MATH_SEMANTICS_RULESET_VERSION,
        "question_type": "M2",
        "policy_version": "2",
        "semantic_class": semantic_class,
        "trigger_operator": operator,
    }


def test_nested_unsupported_operator_is_not_hidden_by_supported_outer_expression() -> None:
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={
            "expected": ["Add", 1, ["Equal", "x", 2]],
            "variables": ["x"],
        },
    )

    assert evaluation.semantic_class == "equation_or_inequality"
    assert evaluation.trigger_operator == "Equal"
    assert evaluation.findings[0].code == "m2_equation_semantics_unsupported"


@pytest.mark.parametrize(
    "expected",
    [
        ["Divide", 1, "x"],
        ["Power", "x", -1],
    ],
)
def test_symbolic_denominator_semantics_are_blocked(expected: object) -> None:
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={"expected": expected, "variables": ["x"]},
    )

    assert evaluation.semantic_class == "domain_restriction"
    assert evaluation.findings[0].code == "m2_domain_semantics_unsupported"


def test_fractional_symbolic_power_is_root_risk() -> None:
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={
            "expected": ["Power", "x", ["Rational", 1, 2]],
            "variables": ["x"],
        },
    )

    assert evaluation.semantic_class == "extraneous_or_missing_root_risk"
    assert evaluation.findings[0].code == "m2_root_semantics_unsupported"


def test_unknown_operator_is_blocked_without_raw_mathjson_in_evidence() -> None:
    expected = ["SecretOperator", ["Add", "private_symbol", 1]]
    evaluation = evaluate_math_semantics(
        question_type="M2",
        policy_version="2",
        rule_json={"expected": expected, "variables": ["private_symbol"]},
    )

    assert evaluation.semantic_class == "unsupported_structure"
    assert evaluation.findings[0].code == "math_semantics_unsupported"
    persisted = json.dumps(
        {
            "signal": evaluation.feature_summary(),
            "finding": evaluation.findings[0].evidence,
        }
    )
    assert "private_symbol" not in persisted
    assert "SecretOperator" not in persisted
    assert evaluation.trigger_operator == "unknown_operator"
    assert json.dumps(expected) not in persisted


def test_non_math_question_is_not_applicable() -> None:
    evaluation = evaluate_math_semantics(
        question_type="E1",
        policy_version="2",
        rule_json={"accepted_answers": ["answer"]},
    )

    assert evaluation.support_status == "not_applicable"
    assert evaluation.semantic_class == "not_applicable"
    assert evaluation.findings == ()
