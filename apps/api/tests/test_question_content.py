import pytest

from edu_grader_api.services.question_content import (
    QUESTION_CONTENT_SCHEMA_VERSION,
    QuestionContentValidationError,
    legacy_projection,
    legacy_question_content,
    validate_question_content,
)


def test_legacy_content_round_trips_prompt_and_reading_material() -> None:
    content = legacy_question_content("What is 2 + 2?", "Read this first.")

    assert content == {
        "stem": [{"kind": "text", "text": "What is 2 + 2?"}],
        "reading_material": [{"kind": "text", "text": "Read this first."}],
        "response": {"kind": "legacy-rule"},
        "explanation": [],
        "metadata": {"grade": None, "difficulty": None, "estimated_minutes": None},
    }
    assert legacy_projection(content) == ("What is 2 + 2?", "Read this first.")
    assert QUESTION_CONTENT_SCHEMA_VERSION == "question-content-v1"


def test_content_rejects_unknown_blocks() -> None:
    with pytest.raises(QuestionContentValidationError, match="question_content_invalid"):
        validate_question_content(
            {
                "stem": [{"kind": "html", "html": "<script>alert(1)</script>"}],
                "reading_material": [],
                "response": {"kind": "legacy-rule"},
                "explanation": [],
                "metadata": {"grade": None, "difficulty": None, "estimated_minutes": None},
            }
        )


def test_content_rejects_unsafe_metadata_keys() -> None:
    with pytest.raises(QuestionContentValidationError, match="question_content_unsafe_metadata"):
        validate_question_content(
            {
                "stem": [],
                "reading_material": [],
                "response": {"kind": "legacy-rule"},
                "explanation": [],
                "metadata": {
                    "grade": None,
                    "difficulty": None,
                    "estimated_minutes": None,
                    "source_url": "https://example.test/private",
                },
            }
        )
