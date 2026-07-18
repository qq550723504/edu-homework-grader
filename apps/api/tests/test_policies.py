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
