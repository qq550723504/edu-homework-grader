from decimal import Decimal

import pytest

from edu_grader_api.services.grade_complexity import (
    CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
    LEGACY_GRADE_COMPLEXITY_RULESET_VERSION,
    evaluate_grade_complexity,
    parse_grade_complexity_rules,
    validate_grade_complexity_rules_document,
)


def test_legacy_grade_complexity_rules_remain_compatible_and_are_versioned_in_evidence() -> None:
    document = {"max_prompt_units": 20, "max_math_operation_nodes": 4}

    assert validate_grade_complexity_rules_document(document) == document
    parsed = parse_grade_complexity_rules(document)

    assert parsed.version == LEGACY_GRADE_COMPLEXITY_RULESET_VERSION
    assert parsed.enforcement == "warning"
    assert parsed.legacy is True
    assert parsed.limits == document


def test_versioned_grade_complexity_rules_are_normalized_with_explicit_defaults() -> None:
    normalized = validate_grade_complexity_rules_document(
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "max_reading_units": 80,
            "max_long_lexical_units": 2,
        }
    )

    assert normalized == {
        "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
        "enforcement": "warning",
        "long_lexical_unit_threshold": 10,
        "max_long_lexical_units": 2,
        "max_reading_units": 80,
    }


@pytest.mark.parametrize(
    "document",
    [
        {"version": "latest", "max_prompt_units": 10},
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "enforcement": "ignore",
        },
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "long_lexical_unit_threshold": 1,
        },
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "max_reading_units": 0,
        },
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "private_model_feature": 3,
        },
    ],
)
def test_versioned_grade_complexity_rules_reject_unsupported_or_unsafe_fields(
    document: object,
) -> None:
    with pytest.raises(ValueError):
        validate_grade_complexity_rules_document(document)


def test_e4_complexity_evaluation_records_reading_reference_and_lexical_signals() -> None:
    evaluation = evaluate_grade_complexity(
        {
            "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
            "enforcement": "blocked",
            "long_lexical_unit_threshold": 8,
            "max_reading_units": 6,
            "max_reading_sentence_units": 4,
            "max_reference_units": 3,
            "max_long_lexical_units": 1,
        },
        prompt="Read and answer.",
        reading_material=(
            "The extraordinarily careful traveller crossed the old bridge. "
            "Everyone arrived safely."
        ),
        reference_texts=("crossed the old bridge", "arrived safely"),
        maximum_numeric_absolute_value=None,
        math_operation_nodes=None,
    )

    assert evaluation.rule_set.version == CURRENT_GRADE_COMPLEXITY_RULESET_VERSION
    assert evaluation.rule_set.enforcement == "blocked"
    assert evaluation.violations == (
        "max_reading_units",
        "max_reading_sentence_units",
        "max_reference_units",
        "max_long_lexical_units",
    )
    summary = evaluation.feature_summary(grade_level="G8", question_type="E4")
    assert summary["lexical_signal"] == {
        "version": "lexical-length-v1",
        "band": "extended",
        "max_unit_length": len("extraordinarily"),
        "long_unit_threshold": 8,
        "long_unit_count": 3,
    }
    assert summary["observations"]["max_reference_units"] == 4
    assert "traveller" not in str(summary)
    assert "bridge" not in str(summary)


def test_numeric_complexity_preserves_decimal_comparison_before_json_safe_summary() -> None:
    evaluation = evaluate_grade_complexity(
        {"max_numeric_absolute_value": 10},
        prompt="Find the value.",
        reading_material="",
        reference_texts=(),
        maximum_numeric_absolute_value=Decimal("10.0000000000000001"),
        math_operation_nodes=2,
    )

    assert evaluation.violations == ("max_numeric_absolute_value",)
    assert evaluation.observations["max_numeric_absolute_value"] > 10
    assert evaluation.observations["max_math_operation_nodes"] == 2
