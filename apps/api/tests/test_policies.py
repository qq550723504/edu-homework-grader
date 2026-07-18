from edu_grader_api.policies import validate_policy


def test_numeric_policy_reports_json_pointer_for_negative_tolerance() -> None:
    errors = validate_policy("M1", "1", {"expected": 5, "tolerance": -1})

    assert errors == [
        {
            "path": "/tolerance",
            "message": "-1 is less than the minimum of 0",
        }
    ]


def test_numeric_policy_rejects_unknown_fields() -> None:
    errors = validate_policy("M1", "1", {"expected": 5, "unexpected": True})

    assert errors == [
        {
            "path": "/",
            "message": "Additional properties are not allowed ('unexpected' was unexpected)",
        }
    ]


def test_initial_policy_set_includes_expression_and_english_foundations() -> None:
    assert validate_policy("M2", "1", {"expected": {"type": "number", "value": "1"}}) == []
    assert validate_policy("E1", "1", {"accepted_answers": ["cat"]}) == []
    assert validate_policy("E4", "1", {"rubric": "Assess the supporting evidence."}) == []
