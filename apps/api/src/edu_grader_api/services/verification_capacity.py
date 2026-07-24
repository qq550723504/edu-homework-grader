"""Versioned, de-identified candidate verification capacity preflight."""

from __future__ import annotations

import json
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
    """Evaluate bounded candidate structure without returning educational content."""

    if not isinstance(candidate, dict):
        return _invalid_evaluation("candidate_not_object")

    traversal = _measure_structure(candidate)
    candidate_bytes = _json_size(candidate)
    rule_json_bytes = _json_size(candidate.get("rule_json"))
    assertions_bytes = _json_size(candidate.get("verification_assertions"))
    if candidate_bytes is None or rule_json_bytes is None or assertions_bytes is None:
        return _invalid_evaluation("candidate_not_serializable")

    scoring_points, evidence_phrases, evidence_phrase_chars = _rubric_observations(
        candidate.get("rule_json")
    )
    observations = {
        "candidate_bytes": candidate_bytes,
        "prompt_chars": _text_length(candidate.get("prompt")),
        "explanation_chars": _text_length(candidate.get("explanation")),
        "reading_material_chars": _text_length(candidate.get("reading_material")),
        "rule_json_bytes": rule_json_bytes,
        "verification_assertions_bytes": assertions_bytes,
        "json_depth": traversal.max_depth,
        "json_nodes": traversal.node_count,
        "scoring_points": scoring_points,
        "evidence_phrases": evidence_phrases,
        "evidence_phrase_chars": evidence_phrase_chars,
        "control_characters": traversal.control_characters,
        "combining_mark_run": traversal.max_combining_mark_run,
    }
    violations = tuple(
        metric
        for metric in _LIMIT_ORDER
        if observations[metric] > _LIMITS[metric]
    )
    load_bucket = _load_bucket(candidate_bytes)
    findings: tuple[VerificationCapacityFinding, ...] = ()
    if violations:
        findings = (
            VerificationCapacityFinding(
                code="candidate_capacity_limit_exceeded",
                evidence={
                    "ruleset_version": VERIFICATION_CAPACITY_RULESET_VERSION,
                    "load_bucket": load_bucket,
                    "violations": list(violations),
                    "observations": {
                        metric: observations[metric] for metric in violations
                    },
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
    while stack:
        current, depth = stack.pop()
        node_count += 1
        max_depth = max(max_depth, depth)
        if isinstance(current, str):
            controls, combining_run = _measure_text(current)
            control_characters += controls
            max_combining_mark_run = max(max_combining_mark_run, combining_run)
        elif isinstance(current, dict):
            for key, item in current.items():
                stack.append((key, depth + 1))
                stack.append((item, depth + 1))
        elif isinstance(current, list | tuple | set):
            stack.extend((item, depth + 1) for item in current)
        if node_count > MAX_JSON_NODES:
            return _TraversalMeasurement(
                node_count=node_count,
                max_depth=max_depth,
                control_characters=control_characters,
                max_combining_mark_run=max_combining_mark_run,
            )
    return _TraversalMeasurement(
        node_count=node_count,
        max_depth=max_depth,
        control_characters=control_characters,
        max_combining_mark_run=max_combining_mark_run,
    )


def _measure_text(value: str) -> tuple[int, int]:
    controls = 0
    current_combining_run = 0
    max_combining_run = 0
    for character in value:
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n", "\r"}:
            controls += 1
        if unicodedata.combining(character):
            current_combining_run += 1
            max_combining_run = max(max_combining_run, current_combining_run)
        else:
            current_combining_run = 0
    return controls, max_combining_run


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


def _json_size(value: object) -> int | None:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (RecursionError, TypeError, ValueError):
        return None
    return len(payload.encode("utf-8"))


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
