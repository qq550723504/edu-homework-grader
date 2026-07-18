from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator


M1_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["expected"],
    "properties": {
        "expected": {"type": "number"},
        "tolerance": {"type": "number", "minimum": 0},
    },
}

M2_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["expected"],
    "properties": {
        "expected": {"type": "object"},
        "variables": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 32},
            "uniqueItems": True,
            "maxItems": 10,
        },
        "required_form": {"enum": ["expanded"]},
        "form_score": {"type": "number", "minimum": 0},
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}

E1_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["accepted_answers"],
    "properties": {
        "accepted_answers": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 2_000},
            "minItems": 1,
            "maxItems": 50,
            "uniqueItems": True,
        },
        "ignore_case": {"type": "boolean"},
        "ignore_terminal_punctuation": {"type": "boolean"},
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}

E4_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["rubric"],
    "properties": {
        "rubric": {"type": "string", "minLength": 1, "maxLength": 10_000},
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}


POLICY_SCHEMAS: dict[tuple[str, str], Mapping[str, Any]] = {
    ("M1", "1"): M1_POLICY_V1,
    ("M2", "1"): M2_POLICY_V1,
    ("E1", "1"): E1_POLICY_V1,
    ("E4", "1"): E4_POLICY_V1,
}


def validate_policy(
    question_type: str,
    policy_version: str,
    rule_json: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Validate a question rule against its platform-owned policy schema."""

    schema = POLICY_SCHEMAS.get((question_type, policy_version))
    if schema is None:
        return [
            {
                "path": "/",
                "message": f"unsupported policy {question_type}@{policy_version}",
            }
        ]

    validator = Draft202012Validator(schema)
    return [
        {"path": _to_json_pointer(error.absolute_path), "message": error.message}
        for error in sorted(validator.iter_errors(rule_json), key=_error_sort_key)
    ]


def _error_sort_key(error: Any) -> tuple[str, ...]:
    return tuple(str(part) for part in error.absolute_path)


def _to_json_pointer(path: Any) -> str:
    parts = [str(part).replace("~", "~0").replace("/", "~1") for part in path]
    return "/" if not parts else "/" + "/".join(parts)
