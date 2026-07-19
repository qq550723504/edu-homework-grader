import logging

from edu_grader_api.logging import get_secure_logger


def test_nested_answer_tokens_and_identity_are_never_emitted(caplog) -> None:
    logger = get_secure_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info(
            "submission.failed",
            extra={
                "fields": {
                    "answer_json": {"answer": "student answer", "school_id": "S-1"},
                    "authorization": "Bearer secret",
                    "email": "student@example.test",
                    "correlation_id": "request-1",
                }
            },
        )

    assert "student answer" not in caplog.text
    assert "Bearer secret" not in caplog.text
    assert "student@example.test" not in caplog.text
    assert "[REDACTED]" in caplog.text
    assert "request-1" in caplog.text


def test_control_characters_are_escaped_before_logging(caplog) -> None:
    logger = get_secure_logger("test")
    with caplog.at_level(logging.INFO):
        logger.info("request.failed", extra={"fields": {"reason": "bad\nforged=entry"}})

    assert "bad\\nforged=entry" in caplog.text
