from edu_grader.english import EnglishExactRequest, grade_english_rule, grade_exact


def test_exact_match_normalizes_case_whitespace_and_terminal_punctuation() -> None:
    result = grade_exact(
        EnglishExactRequest(
            student_answer="  He   went home. ",
            accepted_answers=["he went home"],
            max_score=2,
        )
    )

    assert result.decision == "auto_accepted"
    assert result.score == 2


def test_non_match_is_rejected() -> None:
    result = grade_exact(
        EnglishExactRequest(
            student_answer="He goes home",
            accepted_answers=["He went home"],
        )
    )

    assert result.decision == "auto_rejected"
    assert result.score == 0


def test_e1_v2_matches_normalized_abbreviation() -> None:
    result = grade_english_rule(
        {
            "question_type": "E1",
            "policy_version": "2",
            "rule": {
                "accepted_answers": ["I am", "I'm"],
                "normalization": {
                    "unicode_form": "NFKC",
                    "collapse_whitespace": True,
                    "ignore_case": True,
                    "ignore_terminal_punctuation": True,
                },
                "max_score": 1,
            },
            "answer": {"answer": "  i'm!  "},
        }
    )

    assert result.decision == "auto_accepted"
    assert result.criteria[0].evidence == "matched accepted answer: i'm"


def test_e2_wrong_form_records_the_configured_constraint() -> None:
    result = grade_english_rule(
        {
            "question_type": "E2",
            "policy_version": "1",
            "rule": {
                "lemma": "go",
                "accepted_forms": ["went"],
                "constraints": {"tense": "past"},
                "max_score": 1,
            },
            "answer": {"answer": "go"},
        }
    )

    assert result.decision == "auto_rejected"
    assert [criterion.code for criterion in result.criteria] == ["accepted_form", "tense"]
    assert result.criteria[1].evidence == "configured tense constraint requires past"
