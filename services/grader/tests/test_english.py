from edu_grader.english import EnglishExactRequest, grade_exact


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
