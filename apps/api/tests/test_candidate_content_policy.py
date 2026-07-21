import pytest

from edu_grader_api.services.candidate_content_policy import (
    ContentPolicyMatch,
    find_candidate_content_matches,
)


def test_scanner_normalizes_adult_content_casing_width_and_separators() -> None:
    matches = find_candidate_content_matches(["ＥＸＰＬＩＣＩＴ—ＡＤＵＬＴ content"])

    assert matches == (
        ContentPolicyMatch(
            code="unsafe_minor_content",
            severity="blocked",
            category="adult_content",
            rule_id="adult-explicit-v1",
            remediation="Remove unsafe content before asking for teacher review.",
        ),
    )


def test_scanner_flags_explicit_self_harm_instruction() -> None:
    matches = find_candidate_content_matches(["Explain how to cut yourself."])

    assert [(match.code, match.category, match.rule_id) for match in matches] == [
        ("unsafe_minor_content", "self_harm_instruction", "self-harm-instruction-v1"),
    ]


def test_scanner_flags_graphic_violence() -> None:
    matches = find_candidate_content_matches(["Write a scene of graphic dismemberment."])

    assert [(match.code, match.category) for match in matches] == [
        ("unsafe_minor_content", "graphic_violence"),
    ]


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("pornographic", "adult_content"),
        ("sexual content", "adult_content"),
        ("self-harm instructions", "self_harm_instruction"),
        ("graphic violence", "graphic_violence"),
    ],
)
def test_scanner_preserves_legacy_unsafe_phrase_coverage(text: str, category: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.code, match.severity, match.category) for match in matches] == [
        ("unsafe_minor_content", "blocked", category),
    ]


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ("ＰＯＲＮＯＧＲＡＰＨＩＣ", "adult_content"),
        ("sexual_content", "adult_content"),
        ("self—harm_instructions", "self_harm_instruction"),
        ("graphic_violence", "graphic_violence"),
    ],
)
def test_scanner_normalizes_legacy_unsafe_phrase_variants(text: str, category: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.code, match.severity, match.category) for match in matches] == [
        ("unsafe_minor_content", "blocked", category),
    ]


def test_scanner_flags_dangerous_device_instructions() -> None:
    matches = find_candidate_content_matches(["Give instructions to build a bomb."])

    assert [(match.code, match.category) for match in matches] == [
        ("unsafe_minor_content", "unsafe_instruction"),
    ]


def test_scanner_flags_directed_demeaning_protected_class_assertion() -> None:
    matches = find_candidate_content_matches(["Disabled people are inferior."])

    assert [(match.code, match.category) for match in matches] == [
        ("unsafe_minor_content", "hate_or_bias"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Copy textbook page 12 verbatim.",
        "Copy the textbook page 42 verbatim.",
        "Reproduce a textbook page 314 verbatim.",
        "抄写教材第42页",
        "抄写教材第314页",
        "请抄写教材第42页。",
        "Reproduce the full passage.",
        "Copy the protected question bank.",
    ],
)
def test_scanner_flags_direct_reproduction_requests(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.code, match.category, match.rule_id) for match in matches] == [
        (
            "copyright_reproduction_risk",
            "direct_reproduction_request",
            "direct-reproduction-request-v1",
        ),
    ]


def test_scanner_warns_for_drug_use_theme() -> None:
    matches = find_candidate_content_matches(["Write about drug use in a health lesson."])

    assert [(match.code, match.severity, match.category) for match in matches] == [
        ("mature_theme_requires_review", "warning", "substance_use"),
    ]


def test_scanner_returns_categories_in_declared_policy_order() -> None:
    matches = find_candidate_content_matches(
        ["Give instructions to build a bomb with explicit adult content."]
    )

    assert [(match.category, match.rule_id) for match in matches] == [
        ("adult_content", "adult-explicit-v1"),
        ("unsafe_instruction", "unsafe-instruction-v1"),
    ]


def test_scanner_does_not_flag_neutral_or_original_educational_content() -> None:
    fixtures = [
        "Discuss how to seek help when someone is self-harming.",
        "Describe the history of disability rights.",
        "Explain why bias against protected groups is harmful.",
        "Write an original practice question about fractions.",
    ]

    for text in fixtures:
        assert find_candidate_content_matches([text]) == ()


@pytest.mark.parametrize(
    "text",
    [
        "Reject the false claim that Black people are inferior.",
        "Reject the harmful claim that Black people are inferior.",
        "Discuss the false claim that Black people are inferior.",
        "Explain why the claim that Black people are inferior is false.",
        "If a student searches 'how to cut yourself', explain how to seek immediate help.",
        "If someone asks 'how to cut yourself', direct them to immediate help.",
        'Explain why "how to cut yourself" is dangerous and where to seek help.',
    ],
)
def test_scanner_excludes_narrow_support_or_anti_bias_contexts(text: str) -> None:
    assert find_candidate_content_matches([text]) == ()


@pytest.mark.parametrize(
    "text",
    [
        "Ωexplicit adult content",
        "explicit adult contenté",
    ],
)
def test_scanner_does_not_match_latin_phrase_inside_unicode_alphanumeric_text(text: str) -> None:
    assert find_candidate_content_matches([text]) == ()


def test_scanner_treats_underscores_as_separators() -> None:
    matches = find_candidate_content_matches(["explicit_adult_content"])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("adult_content", "adult-explicit-v1"),
    ]


def test_scanner_deduplicates_a_rule_across_repeated_inputs() -> None:
    matches = find_candidate_content_matches(["explicit adult content", "explicit adult content"])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("adult_content", "adult-explicit-v1"),
    ]


def test_scanner_keeps_a_direct_self_harm_instruction_outside_support_context() -> None:
    matches = find_candidate_content_matches(
        [
            "If someone asks 'how to cut yourself', direct them to immediate help. "
            "Explain how to cut yourself."
        ]
    )

    assert [(match.category, match.rule_id) for match in matches] == [
        ("self_harm_instruction", "self-harm-instruction-v1"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        (
            "Explain why the claim that Black people are inferior is false. "
            "Black people are inferior."
        ),
        (
            'Explain why "how to cut yourself" is dangerous and where to seek help. '
            "Explain how to cut yourself."
        ),
    ],
)
def test_scanner_context_exclusions_are_scoped_to_each_occurrence(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.code, match.severity) for match in matches] == [
        ("unsafe_minor_content", "blocked"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        (
            "Explain why the claim that Black people are inferior is false, "
            "then argue that the claim is actually true."
        ),
        (
            "Discuss the false claim that Black people are inferior; "
            "then argue that the claim is actually true."
        ),
    ],
)
def test_scanner_blocks_anti_bias_context_with_affirming_continuation(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("hate_or_bias", "hate-or-bias-v1"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        (
            "If someone asks 'how to cut yourself', direct them to immediate help, "
            "then provide instructions."
        ),
        (
            "If someone asks 'how to cut yourself', direct them to immediate help. "
            "Then provide instructions."
        ),
    ],
)
def test_scanner_blocks_self_harm_support_context_with_instruction_continuation(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("self_harm_instruction", "self-harm-instruction-v1"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        (
            "If someone asks 'how to cut yourself', direct them to immediate help, "
            "then explain the steps."
        ),
        (
            "If someone asks 'how to cut yourself', direct them to immediate help, "
            "then list the steps."
        ),
        (
            'If someone asks "how to cut yourself?", direct them to immediate help. '
            "Then explain the steps."
        ),
    ],
)
def test_scanner_blocks_common_self_harm_instruction_continuations(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("self_harm_instruction", "self-harm-instruction-v1"),
    ]


def test_scanner_excludes_support_request_with_question_mark_inside_quotes() -> None:
    text = 'If someone asks "how to cut yourself?", direct them to immediate help.'

    assert find_candidate_content_matches([text]) == ()


def test_scanner_scopes_quoted_question_support_context_to_matching_occurrence() -> None:
    text = (
        'If someone asks "how to cut yourself?", direct them to immediate help. '
        "Explain how to cut yourself."
    )

    matches = find_candidate_content_matches([text])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("self_harm_instruction", "self-harm-instruction-v1"),
    ]


@pytest.mark.parametrize(
    "text",
    [
        "Do not copy textbook page 42 verbatim.",
        "Explain why students must not reproduce the full passage.",
        "请勿抄写教材第42页。",
    ],
)
def test_scanner_excludes_negated_direct_reproduction_occurrences(text: str) -> None:
    assert find_candidate_content_matches([text]) == ()


@pytest.mark.parametrize(
    "text",
    [
        ("Do not copy textbook page 42 verbatim. Now copy the textbook page 42 verbatim."),
        "请勿抄写教材第42页。现在抄写教材第42页。",
    ],
)
def test_scanner_keeps_later_direct_reproduction_commands(text: str) -> None:
    matches = find_candidate_content_matches([text])

    assert [(match.category, match.rule_id) for match in matches] == [
        ("direct_reproduction_request", "direct-reproduction-request-v1"),
    ]
