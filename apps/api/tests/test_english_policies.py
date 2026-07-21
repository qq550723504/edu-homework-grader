from edu_grader_api.policies import question_policy_catalog, validate_policy


def test_e1_v2_requires_closed_normalization_configuration() -> None:
    errors = validate_policy(
        "E1",
        "2",
        {
            "accepted_answers": ["I am", "I'm"],
            "normalization": {"ignore_case": True, "unexpected": True},
        },
    )

    assert errors == [
        {
            "path": "/normalization",
            "message": "Additional properties are not allowed ('unexpected' was unexpected)",
        }
    ]


def test_e2_requires_finite_accepted_forms() -> None:
    errors = validate_policy("E2", "1", {"lemma": "go", "constraints": {}})

    assert errors == [{"path": "/", "message": "'accepted_forms' is a required property"}]


def test_e3_requires_grammar_feedback_policy() -> None:
    errors = validate_policy("E3", "1", {"max_score": 1})

    assert errors == [
        {"path": "/", "message": "'grammar_feedback_required' is a required property"}
    ]


def test_e4_requires_nonempty_scoring_points_and_rejects_unknown_fields() -> None:
    empty_errors = validate_policy("E4", "2", {"scoring_points": [], "max_score": 2})
    unknown_errors = validate_policy(
        "E4",
        "2",
        {
            "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
            "max_score": 1,
            "unexpected": True,
        },
    )

    assert empty_errors == [{"path": "/scoring_points", "message": "[] should be non-empty"}]
    assert unknown_errors == [
        {
            "path": "/",
            "message": "Additional properties are not allowed ('unexpected' was unexpected)",
        }
    ]


def test_question_policy_catalog_uses_the_current_english_defaults() -> None:
    catalog = question_policy_catalog()

    assert {"question_type": "E1", "policy_version": "2"} in catalog
    assert {"question_type": "E4", "policy_version": "2"} in catalog
    assert {"question_type": "E4", "policy_version": "1"} not in catalog
    assert catalog == sorted(
        catalog, key=lambda entry: (entry["question_type"], entry["policy_version"])
    )
