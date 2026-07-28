"""Compatibility helpers for the versioned question-content contract."""

from collections.abc import Mapping
from typing import Any


QUESTION_CONTENT_SCHEMA_VERSION = "question-content-v1"

_CONTENT_KEYS = frozenset({"stem", "reading_material", "response", "explanation", "metadata"})
_METADATA_KEYS = frozenset({"grade", "difficulty", "estimated_minutes"})
_UNSAFE_KEY_PARTS = ("url", "token", "secret", "cookie", "authorization")


class QuestionContentValidationError(ValueError):
    """Raised when question content would violate the safe v1 contract."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def legacy_question_content(prompt: str, reading_material: str | None) -> dict[str, Any]:
    """Wrap legacy text columns in the v1 content envelope."""
    content: dict[str, Any] = {
        "stem": [{"kind": "text", "text": prompt}],
        "reading_material": [],
        "response": {"kind": "legacy-rule"},
        "explanation": [],
        "metadata": {
            "grade": None,
            "difficulty": None,
            "estimated_minutes": None,
        },
    }
    if reading_material is not None:
        content["reading_material"] = [{"kind": "text", "text": reading_material}]
    return content


def validate_question_content(content: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a shallowly copied v1 content object."""
    _reject_unsafe_keys(content)
    if set(content) != _CONTENT_KEYS:
        raise QuestionContentValidationError("question_content_invalid")

    validated: dict[str, Any] = {}
    for name in ("stem", "reading_material", "explanation"):
        validated[name] = _validate_text_blocks(content[name])

    if content["response"] != {"kind": "legacy-rule"}:
        raise QuestionContentValidationError("question_content_invalid")
    validated["response"] = {"kind": "legacy-rule"}

    metadata = content["metadata"]
    if not isinstance(metadata, Mapping) or set(metadata) != _METADATA_KEYS:
        raise QuestionContentValidationError("question_content_invalid")
    validated["metadata"] = dict(metadata)
    return validated


def legacy_projection(content: Mapping[str, Any]) -> tuple[str, str | None]:
    """Return the legacy prompt and reading-material columns for a v1 payload."""
    validated = validate_question_content(content)
    prompt = "\n".join(block["text"] for block in validated["stem"])
    reading_blocks = validated["reading_material"]
    reading_material = "\n".join(block["text"] for block in reading_blocks)
    return prompt, reading_material or None


def _validate_text_blocks(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise QuestionContentValidationError("question_content_invalid")

    blocks: list[dict[str, str]] = []
    for block in value:
        if (
            not isinstance(block, Mapping)
            or set(block) != {"kind", "text"}
            or block.get("kind") != "text"
            or not isinstance(block.get("text"), str)
        ):
            raise QuestionContentValidationError("question_content_invalid")
        blocks.append({"kind": "text", "text": block["text"]})
    return blocks


def _reject_unsafe_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise QuestionContentValidationError("question_content_invalid")
            if any(part in key.lower() for part in _UNSAFE_KEY_PARTS):
                raise QuestionContentValidationError("question_content_unsafe_metadata")
            _reject_unsafe_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_unsafe_keys(nested)
