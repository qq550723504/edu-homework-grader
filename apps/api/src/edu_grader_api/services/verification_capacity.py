"""Versioned, de-identified candidate verification capacity preflight."""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Literal

VERIFICATION_CAPACITY_RULESET_VERSION = "verification-capacity-v1"

MAX_CANDIDATE_BYTES = 128 * 1024
MAX_PROMPT_CHARS = 10_000
MAX_EXPLANATION_CHARS = 4_000
MAX_READING_MATERIAL_CHARS = 20_000
MAX_RULE_JSON_BYTES = 64 * 1024
MAX_ASSERTIONS_BYTES = 16 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 4_096
MAX_SCORING_POINTS = 100
MAX_EVIDENCE_PHRASES = 500
MAX_EVIDENCE_PHRASE_CHARS = 1_000
MAX_CONTROL_CHARACTERS = 0
MAX_COMBINING_MARK_RUN = 16

LoadBucket = Literal["small", "medium", "large", "oversize", "invalid"]

_LIMIT_ORDER = (
    "candidate_bytes",
    "prompt_chars",
    "explanation_chars",
    "reading_material_chars",
    "rule_json_bytes",
    "verification_assertions_bytes",
    "json_depth",
    "json_nodes",
    "scoring_points",
    "evidence_phrases",
    "evidence_phrase_chars",
    "control_characters",
    "combining_mark_run",
)
_LIMITS = {
    "candidate_bytes": MAX_CANDIDATE_BYTES,
    "prompt_chars": MAX_PROMPT_CHARS,
    "explanation_chars": MAX_EXPLANATION_CHARS,
    "reading_material_chars": MAX_READING_MATERIAL_CHARS,
    "rule_json_bytes": MAX_RULE_JSON_BYTES,
    "verification_assertions_bytes": MAX_ASSERTIONS_BYTES,
    "json_depth": MAX_JSON_DEPTH,
    "json_nodes": MAX_JSON_NODES,
    "scoring_points": MAX_SCORING_POINTS,
    "evidence_phrases": MAX_EVIDENCE_PHRASES,
    "evidence_phrase_chars": MAX_EVIDENCE_PHRASE_CHARS,
    "control_characters": MAX_CONTROL_CHARACTERS,
    "combining_mark_run": MAX_COMBINING_MARK_RUN,
}
_TEXT_SCAN_LIMIT = MAX_CANDIDATE_BYTES + 1


@dataclass(frozen=True, slots=True)
class VerificationCapacityFinding:
    code: str
    evidence: dict[str, object]
    remediation: str


@dataclass(frozen=True, slots=True)
class VerificationCapacityEvaluation:
    load_bucket: LoadBucket
    observations: dict[str, int]
    violations: tuple[str, ...]
    findings: tuple[VerificationCapacityFinding, ...]

    @property
    def blocked(self) -> bool:
        return bool(self.findings)

    def feature_summary(self) -> dict[str, object]:
        return {
            "availability": "available",
            "version": VERIFICATION_CAPACITY_RULESET_VERSION,
            "load_bucket": self.load_bucket,
            "limits": dict(_LIMITS),
            "observations": dict(self.observations),
            "violations": list(self.violations),
        }


def evaluate_verification_capacity(candidate: object) -> VerificationCapacityEvaluation:
    """Evaluate bounded candidate structure without returning educational content.

    Over-limit JSON byte observations are saturated at ``limit + 1``. Structural
    limits are checked before JSON sizing so wide or recursive payloads cannot
    force unbounded stack growth or full serialization.
    """

    if not isinstance(candidate, dict):
        return _invalid_evaluation("candidate_not_object")

    traversal = _measure_structure(candidate)
    observations = {
        "candidate_bytes": 0,
        "prompt_chars": _text_length(candidate.get("prompt")),
        "explanation_chars": _text_length(candidate.get("explanation")),
        "reading_material_chars": _text_length(candidate.get("reading_material")),
        "rule_json_bytes": 0,
        "verification_assertions_bytes": 0,
        "json_depth": traversal.max_depth,
        "json_nodes": traversal.node_count,
        "scoring_points": 0,
        "evidence_phrases": 0,
        "evidence_phrase_chars": 0,
        "control_characters": traversal.control_characters,
        "combining_mark_run": traversal.max_combining_mark_run,
    }
    if traversal.max_depth > MAX_JSON_DEPTH or traversal.node_count > MAX_JSON_NODES:
        return _evaluation_from_observations(
            load_bucket="oversize",
            observations=observations,
        )

    candidate_bytes = _bounded_json_size(candidate, MAX_CANDIDATE_BYTES)
    rule_json_bytes = _bounded_json_size(candidate.get("rule_json"), MAX_RULE_JSON_BYTES)
    assertions_bytes = _bounded_json_size(
        candidate.get("verification_assertions"), MAX_ASSERTIONS_BYTES
    )
    if candidate_bytes is None or rule_json_bytes is None or assertions_bytes is None:
        return _invalid_evaluation("candidate_not_serializable")

    scoring_points, evidence_phrases, evidence_phrase_chars = _rubric_observations(
        candidate.get("rule_json")
    )
    observations.update(
        {
            "candidate_bytes": candidate_bytes,
            "rule_json_bytes": rule_json_bytes,
            "verification_assertions_bytes": assertions_bytes,
            "scoring_points": scoring_points,
            "evidence_phrases": evidence_phrases,
            "evidence_phrase_chars": evidence_phrase_chars,
        }
    )
    return _evaluation_from_observations(
        load_bucket=_load_bucket(candidate_bytes),
        observations=observations,
    )


def unavailable_verification_capacity_signal(reason: str) -> dict[str, object]:
    return {
        "availability": "unavailable",
        "version": VERIFICATION_CAPACITY_RULESET_VERSION,
        "load_bucket": None,
        "limits": dict(_LIMITS),
        "observations": {},
        "violations": [],
        "reason": reason,
    }


def _evaluation_from_observations(
    *,
    load_bucket: LoadBucket,
    observations: dict[str, int],
) -> VerificationCapacityEvaluation:
    violations = tuple(metric for metric in _LIMIT_ORDER if observations[metric] > _LIMITS[metric])
    findings: tuple[VerificationCapacityFinding, ...] = ()
    if violations:
        findings = (
            VerificationCapacityFinding(
                code="candidate_capacity_limit_exceeded",
                evidence={
                    "ruleset_version": VERIFICATION_CAPACITY_RULESET_VERSION,
                    "load_bucket": load_bucket,
                    "violations": list(violations),
                    "observations": {metric: observations[metric] for metric in violations},
                    "limits": {metric: _LIMITS[metric] for metric in violations},
                },
                remediation=(
                    "Reduce the candidate payload, rubric, nesting, or abnormal Unicode "
                    "before validating it again."
                ),
            ),
        )
    return VerificationCapacityEvaluation(
        load_bucket=load_bucket,
        observations=observations,
        violations=violations,
        findings=findings,
    )


@dataclass(frozen=True, slots=True)
class _TraversalMeasurement:
    node_count: int
    max_depth: int
    control_characters: int
    max_combining_mark_run: int


def _measure_structure(value: object) -> _TraversalMeasurement:
    stack: list[tuple[object, int]] = [(value, 1)]
    node_count = 0
    max_depth = 0
    control_characters = 0
    max_combining_mark_run = 0
    text_characters_scanned = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        max_depth = max(max_depth, depth)
        if node_count > MAX_JSON_NODES:
            return _TraversalMeasurement(
                node_count=MAX_JSON_NODES + 1,
                max_depth=max_depth,
                control_characters=control_characters,
                max_combining_mark_run=max_combining_mark_run,
            )
        if isinstance(current, str):
            remaining_text_budget = max(
                _TEXT_SCAN_LIMIT - text_characters_scanned,
                0,
            )
            controls, combining_run, scanned = _measure_text(
                current,
                max_characters=remaining_text_budget,
            )
            text_characters_scanned += scanned
            control_characters += controls
            max_combining_mark_run = max(max_combining_mark_run, combining_run)
            continue

        if isinstance(current, dict):
            child_count = len(current) * 2
            children = (
                child
                for key, item in current.items()
                for child in ((key, depth + 1), (item, depth + 1))
            )
        elif isinstance(current, list | tuple | set):
            child_count = len(current)
            children = ((item, depth + 1) for item in current)
        else:
            continue

        if child_count and depth + 1 > MAX_JSON_DEPTH:
            return _TraversalMeasurement(
                node_count=node_count,
                max_depth=MAX_JSON_DEPTH + 1,
                control_characters=control_characters,
                max_combining_mark_run=max_combining_mark_run,
            )
        if node_count + len(stack) + child_count > MAX_JSON_NODES:
            return _TraversalMeasurement(
                node_count=MAX_JSON_NODES + 1,
                max_depth=max_depth,
                control_characters=control_characters,
                max_combining_mark_run=max_combining_mark_run,
            )
        stack.extend(children)

    return _TraversalMeasurement(
        node_count=node_count,
        max_depth=max_depth,
        control_characters=control_characters,
        max_combining_mark_run=max_combining_mark_run,
    )


def _measure_text(
    value: str,
    *,
    max_characters: int,
) -> tuple[int, int, int]:
    controls = 0
    current_combining_run = 0
    max_combining_run = 0
    scanned = 0
    for index, character in enumerate(value):
        if index >= max_characters:
            break
        scanned += 1
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n", "\r"}:
            controls += 1
        if unicodedata.combining(character):
            current_combining_run += 1
            max_combining_run = max(max_combining_run, current_combining_run)
        else:
            current_combining_run = 0
    return controls, max_combining_run, scanned


def _rubric_observations(rule_json: object) -> tuple[int, int, int]:
    if not isinstance(rule_json, dict):
        return 0, 0, 0
    scoring_points = rule_json.get("scoring_points")
    if not isinstance(scoring_points, list):
        return 0, 0, 0
    point_count = len(scoring_points)
    phrase_count = 0
    max_phrase_chars = 0
    for point in scoring_points:
        if not isinstance(point, dict):
            continue
        phrases = point.get("evidence_phrases")
        if not isinstance(phrases, list):
            continue
        phrase_count += len(phrases)
        max_phrase_chars = max(
            max_phrase_chars,
            max((len(phrase) for phrase in phrases if isinstance(phrase, str)), default=0),
        )
    return point_count, phrase_count, max_phrase_chars


def _bounded_json_size(value: object, limit: int) -> int | None:
    try:
        return _json_value_size(value, limit)
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        return None


def _json_value_size(value: object, limit: int) -> int:
    if value is None:
        return _bounded_scalar_size(4, limit)
    if isinstance(value, bool):
        return _bounded_scalar_size(4 if value else 5, limit)
    if isinstance(value, str):
        return _json_string_size(value, limit)
    if isinstance(value, int):
        return _bounded_scalar_size(len(str(value)), limit)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite JSON number")
        encoded = json.dumps(value, allow_nan=False, separators=(",", ":"))
        return _bounded_scalar_size(len(encoded), limit)
    if isinstance(value, list | tuple):
        total = 2
        for index, item in enumerate(value):
            total = _bounded_add(total, 1 if index else 0, limit)
            if total > limit:
                return limit + 1
            remaining = limit - total
            child_size = _json_value_size(item, remaining)
            if child_size > remaining:
                return limit + 1
            total += child_size
        return total
    if isinstance(value, dict):
        total = 2
        for index, (key, item) in enumerate(value.items()):
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            total = _bounded_add(total, 1 if index else 0, limit)
            if total > limit:
                return limit + 1
            remaining = limit - total
            key_size = _json_string_size(key, remaining)
            if key_size > remaining:
                return limit + 1
            total += key_size
            total = _bounded_add(total, 1, limit)
            if total > limit:
                return limit + 1
            remaining = limit - total
            child_size = _json_value_size(item, remaining)
            if child_size > remaining:
                return limit + 1
            total += child_size
        return total
    raise TypeError("value is not JSON serializable")


def _json_string_size(value: str, limit: int) -> int:
    total = 2
    if total > limit:
        return limit + 1
    for character in value:
        if character in {'"', "\\"} or character in {"\b", "\f", "\n", "\r", "\t"}:
            encoded_size = 2
        elif ord(character) < 0x20:
            encoded_size = 6
        else:
            encoded_size = len(character.encode("utf-8"))
        total = _bounded_add(total, encoded_size, limit)
        if total > limit:
            return limit + 1
    return total


def _bounded_scalar_size(size: int, limit: int) -> int:
    return size if size <= limit else limit + 1


def _bounded_add(total: int, amount: int, limit: int) -> int:
    if total > limit or amount > limit - total:
        return limit + 1
    return total + amount


def _text_length(value: object) -> int:
    return len(value) if isinstance(value, str) else 0


def _load_bucket(candidate_bytes: int) -> LoadBucket:
    if candidate_bytes <= 16 * 1024:
        return "small"
    if candidate_bytes <= 64 * 1024:
        return "medium"
    if candidate_bytes <= MAX_CANDIDATE_BYTES:
        return "large"
    return "oversize"


def _invalid_evaluation(reason: str) -> VerificationCapacityEvaluation:
    return VerificationCapacityEvaluation(
        load_bucket="invalid",
        observations={},
        violations=("candidate_invalid",),
        findings=(
            VerificationCapacityFinding(
                code="candidate_capacity_payload_invalid",
                evidence={
                    "ruleset_version": VERIFICATION_CAPACITY_RULESET_VERSION,
                    "reason": reason,
                },
                remediation="Provide a JSON-serializable candidate object.",
            ),
        ),
    )
