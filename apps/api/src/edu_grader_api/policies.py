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

M2_POLICY_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["expected"],
    "properties": {
        "expected": {"type": ["array", "string", "number"]},
        "variables": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 32},
            "uniqueItems": True,
            "maxItems": 10,
        },
        "required_form": {"enum": ["expanded"]},
        "form_score": {"type": "number", "minimum": 0, "maximum": 100},
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

E1_POLICY_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["accepted_answers"],
    "properties": {
        "accepted_answers": E1_POLICY_V1["properties"]["accepted_answers"],
        "normalization": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "unicode_form": {"const": "NFKC"},
                "collapse_whitespace": {"type": "boolean"},
                "ignore_case": {"type": "boolean"},
                "ignore_terminal_punctuation": {"type": "boolean"},
            },
        },
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}

_ENGLISH_CONSTRAINT: dict[str, Any] = {"type": ["string", "null"], "maxLength": 64}

E2_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["lemma", "accepted_forms"],
    "properties": {
        "lemma": {"type": "string", "minLength": 1, "maxLength": 128},
        "accepted_forms": {
            "type": "array",
            "items": {"type": "string", "minLength": 1, "maxLength": 256},
            "minItems": 1,
            "maxItems": 50,
            "uniqueItems": True,
        },
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "part_of_speech": _ENGLISH_CONSTRAINT,
                "tense": _ENGLISH_CONSTRAINT,
                "number": _ENGLISH_CONSTRAINT,
                "determiner": _ENGLISH_CONSTRAINT,
            },
        },
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}

E3_POLICY_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["grammar_feedback_required"],
    "properties": {
        "grammar_feedback_required": {"type": "boolean"},
        "accepted_answers": E1_POLICY_V1["properties"]["accepted_answers"],
        "max_score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
    },
}

E4_POLICY_V2: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["scoring_points"],
    "properties": {
        "scoring_points": {
            "type": "array",
            "minItems": 1,
            "maxItems": 20,
            "uniqueItems": True,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "evidence_phrases", "score"],
                "properties": {
                    "id": {"type": "string", "minLength": 1, "maxLength": 64},
                    "evidence_phrases": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 20,
                        "uniqueItems": True,
                        "items": {"type": "string", "minLength": 1, "maxLength": 2_000},
                    },
                    "score": {"type": "number", "exclusiveMinimum": 0, "maximum": 100},
                },
            },
        },
        "similarity_threshold": {"type": "number", "minimum": 0, "maximum": 1},
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
    ("M2", "2"): M2_POLICY_V2,
    ("E1", "1"): E1_POLICY_V1,
    ("E1", "2"): E1_POLICY_V2,
    ("E2", "1"): E2_POLICY_V1,
    ("E3", "1"): E3_POLICY_V1,
    ("E4", "1"): E4_POLICY_V1,
    ("E4", "2"): E4_POLICY_V2,
}

DEFAULT_POLICY_KEYS = frozenset(
    {
        ("M1", "1"),
        ("M2", "2"),
        ("E1", "2"),
        ("E2", "1"),
        ("E3", "1"),
        ("E4", "2"),
    }
)


def question_policy_catalog() -> list[dict[str, str]]:
    """Return the policy versions used as defaults for new authoring flows."""

    return [
        {"question_type": question_type, "policy_version": policy_version}
        for question_type, policy_version in sorted(DEFAULT_POLICY_KEYS)
    ]


def validate_new_question_policy(question_type: str, policy_version: str) -> list[dict[str, str]]:
    """Reject policy versions that must not be used for newly-created questions."""

    if (question_type, policy_version) != ("E4", "1"):
        return []
    return [{"path": "/", "message": "policy E4@1 cannot be used for new questions"}]


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
