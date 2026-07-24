"""Versioned, de-identified grade-complexity rules and signals."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math
import re
from typing import Iterable, Literal, Mapping

CURRENT_GRADE_COMPLEXITY_RULESET_VERSION = "grade-complexity-v1"
LEGACY_GRADE_COMPLEXITY_RULESET_VERSION = "grade-complexity-legacy-v0"
LEXICAL_SIGNAL_VERSION = "lexical-length-v1"

Enforcement = Literal["warning", "blocked"]

_LEGACY_LIMIT_KEYS = frozenset(
    {
        "max_prompt_units",
        "max_sentence_units",
        "max_numeric_absolute_value",
        "max_math_operation_nodes",
    }
)
_VERSIONED_LIMIT_KEYS = frozenset(
    {
        *_LEGACY_LIMIT_KEYS,
        "max_reading_units",
        "max_reading_sentence_units",
        "max_reference_units",
        "max_lexical_unit_length",
        "max_long_lexical_units",
    }
)
_VERSIONED_METADATA_KEYS = frozenset(
    {"version", "enforcement", "long_lexical_unit_threshold"}
)
_DEFAULT_LONG_LEXICAL_UNIT_THRESHOLD = 10
_LIMIT_ORDER = (
    "max_prompt_units",
    "max_sentence_units",
    "max_reading_units",
    "max_reading_sentence_units",
    "max_reference_units",
    "max_lexical_unit_length",
    "max_long_lexical_units",
    "max_numeric_absolute_value",
    "max_math_operation_nodes",
)
_LEXICAL_UNITS = re.compile(
    r"[A-Za-z0-9\u00c0-\u024f\u1e00-\u1eff\u2c60-\u2c7f\ua720-\ua7ff"
    r"\uab30-\uab6f]+(?:'[A-Za-z0-9\u00c0-\u024f\u1e00-\u1eff\u2c60-\u2c7f"
    r"\ua720-\ua7ff\uab30-\uab6f]+)*|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    r"\U00020000-\U0002ebef\U00030000-\U000323af]"
)
_SENTENCE_SEPARATORS = re.compile(r"[.!?。！？]+")


@dataclass(frozen=True, slots=True)
class GradeComplexityRuleSet:
    version: str
    enforcement: Enforcement
    limits: Mapping[str, int]
    long_lexical_unit_threshold: int
    legacy: bool


@dataclass(frozen=True, slots=True)
class GradeComplexityEvaluation:
    rule_set: GradeComplexityRuleSet
    observations: Mapping[str, int | float]
    violations: tuple[str, ...]
    lexical_signal: Mapping[str, int | str]

    def feature_summary(self, *, grade_level: str, question_type: str) -> dict[str, object]:
        return {
            "availability": "available",
            "version": self.rule_set.version,
            "enforcement": self.rule_set.enforcement,
            "legacy_normalized": self.rule_set.legacy,
            "grade_level": grade_level,
            "question_type": question_type,
            "limits": dict(sorted(self.rule_set.limits.items())),
            "observations": dict(sorted(self.observations.items())),
            "violations": list(self.violations),
            "lexical_signal": dict(self.lexical_signal),
        }


def validate_grade_complexity_rules_document(value: object) -> dict[str, object]:
    """Validate an imported rule document while preserving legacy payloads."""

    if not isinstance(value, dict):
        raise ValueError("invalid complexity rules")
    if "version" not in value:
        if set(value) - _LEGACY_LIMIT_KEYS:
            raise ValueError("invalid complexity rules")
        _validate_positive_integer_limits(value)
        return dict(value)

    allowed_keys = _VERSIONED_LIMIT_KEYS | _VERSIONED_METADATA_KEYS
    if set(value) - allowed_keys:
        raise ValueError("invalid complexity rules")
    if value.get("version") != CURRENT_GRADE_COMPLEXITY_RULESET_VERSION:
        raise ValueError("unsupported complexity rules version")
    enforcement = value.get("enforcement", "warning")
    if enforcement not in {"warning", "blocked"}:
        raise ValueError("invalid complexity enforcement")
    threshold = value.get(
        "long_lexical_unit_threshold", _DEFAULT_LONG_LEXICAL_UNIT_THRESHOLD
    )
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, int)
        or threshold < 2
        or threshold > 64
    ):
        raise ValueError("invalid long lexical unit threshold")
    limits = {key: value[key] for key in _VERSIONED_LIMIT_KEYS if key in value}
    _validate_positive_integer_limits(limits)
    return {
        "version": CURRENT_GRADE_COMPLEXITY_RULESET_VERSION,
        "enforcement": enforcement,
        "long_lexical_unit_threshold": threshold,
        **dict(sorted(limits.items())),
    }


def parse_grade_complexity_rules(value: object) -> GradeComplexityRuleSet:
    normalized = validate_grade_complexity_rules_document(value)
    if "version" not in normalized:
        return GradeComplexityRuleSet(
            version=LEGACY_GRADE_COMPLEXITY_RULESET_VERSION,
            enforcement="warning",
            limits=normalized,
            long_lexical_unit_threshold=_DEFAULT_LONG_LEXICAL_UNIT_THRESHOLD,
            legacy=True,
        )
    enforcement = normalized["enforcement"]
    assert enforcement in {"warning", "blocked"}
    return GradeComplexityRuleSet(
        version=str(normalized["version"]),
        enforcement=enforcement,
        limits={
            key: int(normalized[key])
            for key in _VERSIONED_LIMIT_KEYS
            if key in normalized
        },
        long_lexical_unit_threshold=int(normalized["long_lexical_unit_threshold"]),
        legacy=False,
    )


def evaluate_grade_complexity(
    rules_document: object,
    *,
    prompt: str,
    reading_material: str,
    reference_texts: Iterable[str],
    maximum_numeric_absolute_value: int | float | Decimal | None,
    math_operation_nodes: int | None,
) -> GradeComplexityEvaluation:
    rule_set = parse_grade_complexity_rules(rules_document)
    references = tuple(text for text in reference_texts if isinstance(text, str))
    all_texts = (prompt, reading_material, *references)
    lexical_units = [
        unit for text in all_texts if text for unit in _LEXICAL_UNITS.findall(text)
    ]
    latin_units = [
        unit for unit in lexical_units if any(character.isalpha() for character in unit)
    ]
    max_lexical_length = max((len(unit) for unit in latin_units), default=0)
    long_lexical_units = sum(
        len(unit) >= rule_set.long_lexical_unit_threshold for unit in latin_units
    )
    observations: dict[str, int | float] = {
        "max_prompt_units": _lexical_unit_count(prompt),
        "max_sentence_units": _max_sentence_units(prompt),
        "max_reading_units": _lexical_unit_count(reading_material),
        "max_reading_sentence_units": _max_sentence_units(reading_material),
        "max_reference_units": max(
            (_lexical_unit_count(text) for text in references), default=0
        ),
        "max_lexical_unit_length": max_lexical_length,
        "max_long_lexical_units": long_lexical_units,
    }
    numeric_value = _finite_nonnegative_number(maximum_numeric_absolute_value)
    if numeric_value is not None:
        observations["max_numeric_absolute_value"] = numeric_value
    if (
        math_operation_nodes is not None
        and not isinstance(math_operation_nodes, bool)
        and isinstance(math_operation_nodes, int)
        and math_operation_nodes >= 0
    ):
        observations["max_math_operation_nodes"] = math_operation_nodes

    violations = tuple(
        metric
        for metric in _LIMIT_ORDER
        if metric in rule_set.limits
        and metric in observations
        and observations[metric] > rule_set.limits[metric]
    )
    lexical_signal = {
        "version": LEXICAL_SIGNAL_VERSION,
        "band": _lexical_length_band(
            max_lexical_length,
            long_lexical_units,
            rule_set.long_lexical_unit_threshold,
        ),
        "max_unit_length": max_lexical_length,
        "long_unit_threshold": rule_set.long_lexical_unit_threshold,
        "long_unit_count": long_lexical_units,
    }
    return GradeComplexityEvaluation(
        rule_set=rule_set,
        observations=observations,
        violations=violations,
        lexical_signal=lexical_signal,
    )


def unavailable_grade_complexity_signal(reason: str) -> dict[str, object]:
    return {
        "availability": "unavailable",
        "version": None,
        "enforcement": None,
        "legacy_normalized": False,
        "grade_level": None,
        "question_type": None,
        "limits": {},
        "observations": {},
        "violations": [],
        "lexical_signal": {
            "version": LEXICAL_SIGNAL_VERSION,
            "band": None,
            "max_unit_length": None,
            "long_unit_threshold": None,
            "long_unit_count": None,
        },
        "reason": reason,
    }


def _validate_positive_integer_limits(limits: Mapping[str, object]) -> None:
    for limit in limits.values():
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("invalid complexity limit")


def _lexical_unit_count(text: str) -> int:
    return len(_LEXICAL_UNITS.findall(text))


def _max_sentence_units(text: str) -> int:
    return max(
        (_lexical_unit_count(sentence) for sentence in _SENTENCE_SEPARATORS.split(text)),
        default=0,
    )


def _finite_nonnegative_number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        numeric = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return int(numeric) if numeric.is_integer() else numeric


def _lexical_length_band(max_length: int, long_count: int, long_threshold: int) -> str:
    if max_length == 0:
        return "not_observed"
    if max_length < long_threshold and long_count == 0:
        return "bounded"
    if long_count <= 3:
        return "extended"
    return "dense"
