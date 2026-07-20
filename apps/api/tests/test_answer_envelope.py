import pytest

from edu_grader_api.answer_envelope import (
    AnswerEnvelopeValidationError,
    migrate_legacy_answer_envelope,
    normalize_answer_envelope,
)


def test_text_answer_envelope_is_normalized_and_legacy_value_is_rejected() -> None:
    assert normalize_answer_envelope({"format": "text-v1", "text": "  He went home.  "}) == {
        "format": "text-v1",
        "text": "He went home.",
    }

    with pytest.raises(AnswerEnvelopeValidationError, match="unsupported_answer_envelope"):
        normalize_answer_envelope({"value": "He went home."})


def test_empty_text_and_mathjson_answers_use_versioned_envelopes() -> None:
    assert normalize_answer_envelope({"format": "text-v1", "text": "  "}) == {
        "format": "text-v1",
        "text": "",
    }
    assert normalize_answer_envelope(
        {"format": "mathjson-v1", "latex": "x+1", "mathjson": ["Add", "x", 1]},
        expected_format="mathjson-v1",
    ) == {"format": "mathjson-v1", "latex": "x+1", "mathjson": ["Add", "x", 1]}


def test_migration_rewrites_recognized_legacy_answer_shapes() -> None:
    assert migrate_legacy_answer_envelope({"value": "5"}) == {"format": "text-v1", "text": "5"}
    assert migrate_legacy_answer_envelope({"answer": "The bridge closed."}) == {
        "format": "text-v1",
        "text": "The bridge closed.",
    }
    assert migrate_legacy_answer_envelope(
        {"answer": {"format": "mathjson-v1", "latex": "x+1", "mathjson": ["Add", "x", 1]}}
    ) == {"format": "mathjson-v1", "latex": "x+1", "mathjson": ["Add", "x", 1]}
