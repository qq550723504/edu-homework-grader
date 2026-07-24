"""Deterministic verification for AI-generated candidate-question drafts."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Literal, Protocol
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationJob,
    GenerationValidationRun,
    Question,
    QuestionVersion,
    ValidationFinding,
    ValidationFindingSeverity,
    ValidationRunStatus,
    VersionStatus,
)
from ..policies import validate_policy
from ..settings import settings
from .candidate_content_policy import (
    CONTENT_POLICY_VERSION,
    find_candidate_content_matches,
)
from .grade_complexity import (
    evaluate_grade_complexity,
    unavailable_grade_complexity_signal,
)
from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .math_semantics import evaluate_math_semantics, unavailable_math_semantics_signal
from .objective_prerequisites import (
    evaluate_objective_prerequisite_alignment,
    unavailable_objective_prerequisite_signal,
)
from .question_fingerprints import FINGERPRINT_VERSION, PromptFingerprints, fingerprint_prompt
from .questions import GradeResult

VALIDATOR_VERSION = "verification-v8"
RULESET_VERSION = "rules-v8"
_SEMANTIC_CHUNK_SIZE = 128
_DUPLICATE_REMEDIATION = "Revise the prompt to make the candidate meaningfully distinct."
_WHITESPACE = re.compile(r"\s+")
_E2_TERMINAL_PUNCTUATION = re.compile(r"[.!?。！？]+$")
_M1_PROBE_TEXT_LIMIT = 100
# Mirrors the Grader's public safe-AST contract without importing its service package.
_M2_SAFE_AST_MAX_DEPTH = 20
_M2_SAFE_AST_MAX_NODES = 100
_LEXICAL_UNITS = re.compile(
    r"[A-Za-z0-9\u00c0-\u024f\u1e00-\u1eff\u2c60-\u2c7f\ua720-\ua7ff\uab30-\uab6f]+(?:'[A-Za-z0-9\u00c0-\u024f\u1e00-\u1eff\u2c60-\u2c7f\ua720-\ua7ff\uab30-\uab6f]+)*|[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002ebef\U00030000-\U000323af]"
)
_SENTENCE_SEPARATORS = re.compile(r"[.!?。！？]+")
_M2_AST_FIELDS_BY_TYPE = {
    "add": frozenset({"type", "args"}),
    "mul": frozenset({"type", "args"}),
    "neg": frozenset({"type", "arg"}),
    "div": frozenset({"type", "numerator", "denominator"}),
    "pow": frozenset({"type", "base", "exponent"}),
    "number": frozenset({"type", "value"}),
    "symbol": frozenset({"type", "name"}),
}
_GRADER_DECISIONS = frozenset({"auto_accepted", "auto_rejected", "partial", "needs_review"})
_RULE_BASED_DIFFICULTY_VERSION = "rule-based-difficulty-v1"
_QUESTION_TYPE_DIFFICULTY_BASELINES = {
    "M1": 0.20,
    "M2": 0.30,
    "E1": 0.30,
    "E2": 0.35,
    "E3": 0.45,
    "E4": 0.50,
}
_DEFAULT_QUESTION_TYPE_DIFFICULTY_BASELINE = 0.25
_PROMPT_UNITS_DIFFICULTY_WEIGHT = 0.18
_SENTENCE_UNITS_DIFFICULTY_WEIGHT = 0.12
_NUMERIC_MAGNITUDE_DIFFICULTY_WEIGHT = 0.20
_M2_OPERATION_NODES_DIFFICULTY_WEIGHT = 0.15
_PROMPT_UNITS_DIFFICULTY_SCALE = 100
_SENTENCE_UNITS_DIFFICULTY_SCALE = 30
_NUMERIC_MAGNITUDE_DIFFICULTY_SCALE = 6
_M2_OPERATION_NODES_DIFFICULTY_SCALE = 12


class VerificationGraderClient(Protocol):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]: ...

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult: ...

    def semantic_similarity(
        self, query: str, comparisons: list[str]
    ) -> SemanticSimilarityResult: ...


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    severity: ValidationFindingSeverity
    evidence: dict[str, object]
    remediation: str


@dataclass(frozen=True)
class _CandidateEvaluation:
    findings: list[VerificationFinding]
    duplicate_feature_summary: dict[str, object]
    difficulty_signal: dict[str, object]
    grade_complexity_signal: dict[str, object]
    objective_prerequisite_signal: dict[str, object]
    math_semantics_signal: dict[str, object]


@dataclass(frozen=True)
class _M1Probe:
    name: str
    text: str
    expects_acceptance: bool


@dataclass(frozen=True)
class _M2Probe:
    name: str
    mathjson: object
    decisions: frozenset[str]
    score_kind: Literal["full", "zero"]


def run_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    grader_client: VerificationGraderClient,
) -> GenerationValidationRun:
    """Evaluate a candidate and append a new, immutable verification result."""

    if revision.generated_question_draft_id != draft.id:
        raise ValueError("candidate revision does not belong to the draft")
    evaluated_revision_id = revision.id
    evaluated_revision_hash = revision.content_hash
    candidate = deepcopy(revision.candidate_json)
    duplicate_threshold = _validated_duplicate_threshold()
    prompt = candidate.get("prompt")
    duplicate_snapshot = _empty_duplicate_snapshot(
        duplicate_threshold,
        prompt if isinstance(prompt, str) else "",
    )
    try:
        job = session.get(GenerationJob, draft.job_id)
        if job is not None and isinstance(prompt, str):
            duplicate_snapshot = _capture_duplicate_snapshot(
                session,
                draft=draft,
                tenant_id=job.tenant_id,
                prompt=prompt,
                threshold=duplicate_threshold,
            )
        evaluation = _evaluate_candidate(
            session,
            draft=draft,
            candidate=candidate,
            grader_client=grader_client,
            duplicate_snapshot=duplicate_snapshot,
        )
    except Exception:
        evaluation = _CandidateEvaluation(
            findings=[
                VerificationFinding(
                    code="validator_unavailable",
                    severity=ValidationFindingSeverity.BLOCKED,
                    evidence={"category": "internal_validation_error"},
                    remediation=(
                        "Retry validation. If the problem continues, contact an administrator."
                    ),
                )
            ],
            duplicate_feature_summary=_duplicate_feature_summary(duplicate_snapshot),
            difficulty_signal=_unavailable_difficulty_signal(),
            grade_complexity_signal=unavailable_grade_complexity_signal("validator_unavailable"),
            objective_prerequisite_signal=unavailable_objective_prerequisite_signal(
                "validator_unavailable"
            ),
            math_semantics_signal=unavailable_math_semantics_signal("validator_unavailable"),
        )
    return _persist_run(
        session,
        draft=draft,
        evaluated_revision_id=evaluated_revision_id,
        evaluated_revision_hash=evaluated_revision_hash,
        findings=evaluation.findings,
        duplicate_feature_summary=evaluation.duplicate_feature_summary,
        difficulty_signal=evaluation.difficulty_signal,
        grade_complexity_signal=evaluation.grade_complexity_signal,
        objective_prerequisite_signal=evaluation.objective_prerequisite_signal,
        math_semantics_signal=evaluation.math_semantics_signal,
    )


def _evaluate_candidate(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    candidate: dict[str, object],
    grader_client: VerificationGraderClient,
    duplicate_snapshot: _DuplicateSnapshot,
) -> _CandidateEvaluation:
    job = session.get(GenerationJob, draft.job_id)
    if job is None:
        raise ValueError("candidate generation job was not found")
    revision = job.curriculum_objective_revision
    findings: list[VerificationFinding] = []
    grade_complexity_signal = unavailable_grade_complexity_signal("candidate_not_evaluated")
    objective_prerequisite_signal = unavailable_objective_prerequisite_signal(
        "candidate_not_evaluated"
    )
    math_semantics_signal = unavailable_math_semantics_signal("candidate_not_evaluated")

    if (
        revision.status is not CurriculumRevisionStatus.ACTIVE
        or revision.objective.status is not CurriculumProfileStatus.ACTIVE
        or revision.objective.profile.status is not CurriculumProfileStatus.ACTIVE
    ):
        findings.append(
            _blocked(
                "curriculum_revision_inactive",
                {"revision_status": revision.status.value},
                "Use an active curriculum objective revision.",
            )
        )

    if candidate.get("objective_revision_id") != str(job.curriculum_objective_revision_id):
        findings.append(
            _blocked(
                "curriculum_objective_mismatch",
                {"expected_objective_revision_id": str(job.curriculum_objective_revision_id)},
                "Regenerate the candidate for the selected curriculum objective.",
            )
        )

    prerequisite_evaluation = evaluate_objective_prerequisite_alignment(
        session,
        target_revision=revision,
        candidate_knowledge_point=candidate.get("knowledge_point"),
    )
    findings.extend(
        VerificationFinding(
            code=finding.code,
            severity=ValidationFindingSeverity(finding.severity),
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in prerequisite_evaluation.findings
    )
    objective_prerequisite_signal = prerequisite_evaluation.feature_summary()

    difficulty = candidate.get("difficulty")
    if (
        not _is_finite_number(difficulty)
        or difficulty < revision.difficulty_min
        or difficulty > revision.difficulty_max
    ):
        findings.append(
            _blocked(
                "difficulty_out_of_range",
                {
                    "difficulty_min": revision.difficulty_min,
                    "difficulty_max": revision.difficulty_max,
                },
                "Set the candidate difficulty within the curriculum objective range.",
            )
        )

    question_type = candidate.get("question_type")
    if not isinstance(question_type, str) or question_type not in revision.allowed_question_types:
        findings.append(
            _blocked(
                "question_type_not_allowed",
                {"allowed_question_types": sorted(revision.allowed_question_types)},
                "Choose a question type allowed by the curriculum objective.",
            )
        )

    policy_version = candidate.get("policy_version")
    rule_json = candidate.get("rule_json")
    math_semantics_evaluation = evaluate_math_semantics(
        question_type=question_type,
        policy_version=policy_version,
        rule_json=rule_json,
    )
    findings.extend(
        VerificationFinding(
            code=finding.code,
            severity=ValidationFindingSeverity.BLOCKED,
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in math_semantics_evaluation.findings
    )
    math_semantics_signal = math_semantics_evaluation.feature_summary()
    math_semantics_blocked = bool(math_semantics_evaluation.findings)
    policy_errors = (
        validate_policy(question_type, policy_version, rule_json)
        if isinstance(question_type, str)
        and isinstance(policy_version, str)
        and isinstance(rule_json, dict)
        else [{"path": "/", "message": "candidate policy fields are invalid"}]
    )
    if policy_errors:
        findings.append(
            _blocked(
                "policy_schema_invalid",
                {"question_type": question_type if isinstance(question_type, str) else None},
                "Correct the question rule so it matches its grading policy.",
            )
        )

    prompt = candidate.get("prompt")
    explanation = candidate.get("explanation")
    reading_material = candidate.get("reading_material")
    if (
        not isinstance(prompt, str)
        or not prompt.strip()
        or len(prompt) > 10_000
        or not isinstance(explanation, str)
        or not explanation.strip()
        or len(explanation) > 4_000
    ):
        findings.append(
            _blocked(
                "prompt_or_explanation_invalid",
                {
                    "prompt_present": isinstance(prompt, str),
                    "explanation_present": isinstance(explanation, str),
                },
                "Provide a non-empty, bounded prompt and explanation.",
            )
        )

    findings.extend(
        _safety_findings(
            prompt if isinstance(prompt, str) else "",
            explanation if isinstance(explanation, str) else "",
            reading_material if isinstance(reading_material, str) else "",
            *(_text_values(rule_json) if isinstance(rule_json, dict) else []),
        )
    )
    m2_findings: list[VerificationFinding] = []
    normalized_m2_ast: dict[str, object] | None = None
    if (
        question_type == "M2"
        and isinstance(rule_json, dict)
        and not policy_errors
        and not math_semantics_blocked
    ):
        m2_findings, normalized_m2_ast = _m2_findings(
            rule_json,
            policy_version,
            explanation,
            candidate.get("verification_assertions"),
            job.prompt_version == "generator-v3",
            grader_client,
        )

    if isinstance(prompt, str):
        findings.extend(
            _duplicate_findings(
                session,
                draft=draft,
                tenant_id=job.tenant_id,
                prompt=prompt,
                grader_client=grader_client,
                _snapshot=duplicate_snapshot,
            )
        )
    if (
        not policy_errors
        and not math_semantics_blocked
        and isinstance(rule_json, dict)
        and isinstance(prompt, str)
    ):
        grade_level = revision.objective.grade_mapping.internal_level
        try:
            complexity_findings, grade_complexity_signal = _grade_complexity_evaluation(
                rules=revision.objective.grade_mapping.complexity_rules_json,
                grade_level=grade_level,
                prompt=prompt,
                reading_material=reading_material if isinstance(reading_material, str) else "",
                question_type=question_type,
                rule_json=rule_json,
                normalized_m2_ast=normalized_m2_ast,
            )
        except ValueError:
            findings.append(
                _blocked(
                    "grade_complexity_rules_invalid",
                    {"grade_level": grade_level},
                    "Correct the persisted grade complexity rules before validating candidates.",
                )
            )
            grade_complexity_signal = unavailable_grade_complexity_signal("rules_invalid")
        else:
            findings.extend(complexity_findings)

    if (
        question_type == "M1"
        and isinstance(rule_json, dict)
        and not policy_errors
        and not math_semantics_blocked
    ):
        findings.extend(
            _m1_findings(
                rule_json,
                policy_version,
                explanation,
                candidate.get("verification_assertions"),
                job.prompt_version == "generator-v3",
                grader_client,
            )
        )
    findings.extend(m2_findings)
    if question_type == "E2" and isinstance(rule_json, dict) and not policy_errors:
        findings.extend(_e2_findings(rule_json, policy_version, grader_client))
    if (
        question_type == "E3"
        and isinstance(rule_json, dict)
        and isinstance(prompt, str)
        and not policy_errors
    ):
        findings.extend(_e3_findings(rule_json, policy_version, prompt, grader_client))
    if question_type == "E4" and isinstance(rule_json, dict) and not policy_errors:
        findings.extend(_e4_findings(rule_json, policy_version, reading_material, grader_client))
    if question_type == "E1" and isinstance(rule_json, dict):
        findings.extend(_e1_findings(rule_json))
    return _CandidateEvaluation(
        findings=findings,
        duplicate_feature_summary=_duplicate_feature_summary(duplicate_snapshot),
        difficulty_signal=_rule_based_difficulty_signal(
            target_difficulty=difficulty,
            curriculum_range=(revision.difficulty_min, revision.difficulty_max),
            prompt=prompt if isinstance(prompt, str) else "",
            question_type=question_type,
            rule_json=rule_json if isinstance(rule_json, dict) else {},
            normalized_m2_ast=normalized_m2_ast,
        ),
        grade_complexity_signal=grade_complexity_signal,
        objective_prerequisite_signal=objective_prerequisite_signal,
        math_semantics_signal=math_semantics_signal,
    )


def _m1_findings(
    rule_json: dict[str, object],
    policy_version: object,
    explanation: object,
    assertions: object,
    assertions_required: bool,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    if policy_version != "1":
        return []
    expected = rule_json.get("expected")
    tolerance = rule_json.get("tolerance", 0)
    if not _is_finite_number(expected) or not _is_finite_number(tolerance) or tolerance < 0:
        return [
            _blocked(
                "m1_answer_invalid",
                {
                    "expected_is_numeric": _is_finite_number(expected),
                    "tolerance_is_valid": _is_finite_number(tolerance),
                },
                "Provide a finite numeric expected answer and a non-negative tolerance.",
            )
        ]
    if assertions_required or assertions is not None:
        consistency_findings = _m1_consistency_findings(rule_json, explanation, assertions)
        if consistency_findings:
            return consistency_findings
    try:
        probes = _m1_probes(expected, tolerance)
    except (InvalidOperation, ValueError):
        return [
            _blocked(
                "m1_answer_invalid",
                {"reason": "probe_construction"},
                "Provide a finite numeric expected answer and a non-negative tolerance.",
            )
        ]
    remediation = "Correct the numeric rule so its boundary probes match the grading policy."
    first_failure: str | None = None
    for probe in probes:
        try:
            result = grader_client.grade(
                "M1",
                rule_json,
                {"format": "text-v1", "text": probe.text},
                policy_version="1",
            )
            score = result.score
            score_is_finite = (
                not isinstance(score, bool)
                and isinstance(score, int | float)
                and math.isfinite(score)
            )
            if not score_is_finite:
                probe_passed = False
            else:
                probe_passed = (
                    result.decision == "auto_accepted" and score > 0
                    if probe.expects_acceptance
                    else result.decision == "auto_rejected" and score == 0
                )
        except Exception:
            probe_passed = False
        if not probe_passed and first_failure is None:
            first_failure = probe.name
    if first_failure is not None:
        return [_blocked("m1_grader_probe_failed", {"probe": first_failure}, remediation)]
    return []


def _m1_consistency_findings(
    rule_json: dict[str, object], explanation: object, assertions: object
) -> list[VerificationFinding]:
    assertion_values = _assertion_values(assertions, question_type="M1")
    if isinstance(assertion_values, VerificationFinding):
        return [assertion_values]
    final_answer_text, _final_answer_mathjson, declared_max_score = assertion_values
    try:
        assertion_answer = Decimal(final_answer_text)
        expected_answer = Decimal(str(rule_json["expected"]))
    except (InvalidOperation, KeyError, ValueError):
        return [_unsupported_consistency_finding("M1", "final_answer_text")]
    if not assertion_answer.is_finite() or assertion_answer != expected_answer:
        return [_answer_explanation_inconsistent_finding("M1", "final_answer_text")]
    if not _has_explanation_suffix(explanation, final_answer_text):
        return [_answer_explanation_inconsistent_finding("M1", "explanation_suffix")]
    if not math.isclose(declared_max_score, 1, rel_tol=0, abs_tol=1e-9):
        return [_score_total_inconsistent_finding("M1")]
    return []


def _m1_probes(expected: float, tolerance: float) -> tuple[_M1Probe, ...]:
    try:
        expected_decimal = Decimal(str(expected))
        tolerance_decimal = Decimal(str(tolerance))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("M1 probe construction failed") from error
    if not expected_decimal.is_finite() or not tolerance_decimal.is_finite():
        raise ValueError("M1 probe values must be finite")
    unit = Decimal(1)
    with localcontext() as context:
        context.prec = _m1_probe_precision(expected_decimal, tolerance_decimal, unit)
        lower_boundary = expected_decimal - tolerance_decimal
        upper_boundary = expected_decimal + tolerance_decimal
        values = (
            ("expected_answer", expected_decimal, True),
            ("empty_answer", None, False),
            ("lower_tolerance_boundary", lower_boundary, True),
            ("upper_tolerance_boundary", upper_boundary, True),
            ("below_tolerance_boundary", lower_boundary - unit, False),
            ("above_tolerance_boundary", upper_boundary + unit, False),
        )
    probes = tuple(
        _M1Probe(name, "" if value is None else _m1_probe_text(value), accepts)
        for name, value, accepts in values
    )
    if any(len(probe.text) > _M1_PROBE_TEXT_LIMIT for probe in probes):
        raise ValueError("M1 probe exceeds the numeric answer envelope")
    return probes


def _m1_probe_precision(*values: Decimal) -> int:
    nonzero_values = tuple(value for value in values if value)
    significant_precision = (
        max(value.adjusted() for value in nonzero_values)
        - min(value.as_tuple().exponent for value in nonzero_values)
        + 1
    )
    precision = significant_precision + 1
    if precision > _M1_PROBE_TEXT_LIMIT + 1:
        raise ValueError("M1 probe precision exceeds the numeric answer envelope")
    return max(precision, 1)


def _m1_probe_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("M1 probe value must be finite")
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits), 1)
        normalized = value.normalize()
    return "0" if normalized == 0 else str(normalized)


def _grade_complexity_findings(
    *,
    rules: dict[str, object],
    grade_level: str,
    prompt: str,
    question_type: object,
    rule_json: dict[str, object],
    normalized_m2_ast: dict[str, object] | None,
    reading_material: str = "",
) -> list[VerificationFinding]:
    """Return stable findings while preserving the legacy helper contract."""

    findings, _signal = _grade_complexity_evaluation(
        rules=rules,
        grade_level=grade_level,
        prompt=prompt,
        reading_material=reading_material,
        question_type=question_type,
        rule_json=rule_json,
        normalized_m2_ast=normalized_m2_ast,
    )
    return findings


def _grade_complexity_evaluation(
    *,
    rules: object,
    grade_level: str,
    prompt: str,
    reading_material: str,
    question_type: object,
    rule_json: dict[str, object],
    normalized_m2_ast: dict[str, object] | None,
) -> tuple[list[VerificationFinding], dict[str, object]]:
    observations = _complexity_observations(
        prompt=prompt,
        question_type=question_type,
        rule_json=rule_json,
        normalized_m2_ast=normalized_m2_ast,
    )
    evaluation = evaluate_grade_complexity(
        rules,
        prompt=prompt,
        reading_material=reading_material,
        reference_texts=_grade_complexity_reference_texts(question_type, rule_json),
        maximum_numeric_absolute_value=observations.get("max_numeric_absolute_value"),
        math_operation_nodes=(
            int(observations["max_math_operation_nodes"])
            if "max_math_operation_nodes" in observations
            else None
        ),
    )
    findings: list[VerificationFinding] = []
    for metric in evaluation.violations:
        observed = evaluation.observations[metric]
        limit = evaluation.rule_set.limits[metric]
        evidence: dict[str, object] = {
            "grade_level": grade_level,
            "metric": metric,
            "observed": _complexity_observed_value(observed),
            "limit": limit,
        }
        if evaluation.rule_set.legacy:
            code = "grade_complexity_warning"
            severity = ValidationFindingSeverity.WARNING
        else:
            evidence.update(
                {
                    "ruleset_version": evaluation.rule_set.version,
                    "enforcement": evaluation.rule_set.enforcement,
                }
            )
            blocked = evaluation.rule_set.enforcement == "blocked"
            code = "grade_complexity_blocked" if blocked else "grade_complexity_warning"
            severity = (
                ValidationFindingSeverity.BLOCKED if blocked else ValidationFindingSeverity.WARNING
            )
        findings.append(
            VerificationFinding(
                code=code,
                severity=severity,
                evidence=evidence,
                remediation="Revise the candidate to fit the selected grade complexity limit.",
            )
        )
    return findings, evaluation.feature_summary(
        grade_level=grade_level,
        question_type=question_type if isinstance(question_type, str) else "unknown",
    )


def _grade_complexity_reference_texts(
    question_type: object, rule_json: dict[str, object]
) -> tuple[str, ...]:
    if question_type == "E3":
        accepted_answers = rule_json.get("accepted_answers")
        if isinstance(accepted_answers, list):
            return tuple(value for value in accepted_answers if isinstance(value, str))
    if question_type == "E4":
        scoring_points = rule_json.get("scoring_points")
        if isinstance(scoring_points, list):
            return tuple(
                phrase
                for point in scoring_points
                if isinstance(point, dict)
                for phrases in (point.get("evidence_phrases"),)
                if isinstance(phrases, list)
                for phrase in phrases
                if isinstance(phrase, str)
            )
    return ()


def _complexity_observations(
    *,
    prompt: str,
    question_type: object,
    rule_json: dict[str, object],
    normalized_m2_ast: dict[str, object] | None,
) -> dict[str, Decimal | int]:
    """Return only safe, already-validated complexity observations for a candidate."""

    observed_metrics: dict[str, Decimal | int] = {
        "max_prompt_units": _lexical_unit_count(prompt),
        "max_sentence_units": _max_sentence_units(prompt),
    }
    if question_type == "M1":
        numeric_values = [
            abs(Decimal(str(value)))
            for value in (rule_json.get("expected"), rule_json.get("tolerance", 0))
            if _is_finite_number(value)
        ]
        if numeric_values:
            observed_metrics["max_numeric_absolute_value"] = max(numeric_values)
    elif question_type == "M2" and normalized_m2_ast is not None:
        maximum_numeric_value, operation_nodes = _m2_complexity_metrics(normalized_m2_ast)
        if maximum_numeric_value is not None:
            observed_metrics["max_numeric_absolute_value"] = maximum_numeric_value
        observed_metrics["max_math_operation_nodes"] = operation_nodes
    return observed_metrics


def _rule_based_difficulty_signal(
    *,
    target_difficulty: object,
    curriculum_range: tuple[object, object],
    prompt: str,
    question_type: object,
    rule_json: dict[str, object],
    normalized_m2_ast: dict[str, object] | None,
) -> dict[str, object]:
    """Return a deterministic, JSON-safe difficulty estimate without candidate text or rules."""

    try:
        observations = _complexity_observations(
            prompt=prompt,
            question_type=question_type,
            rule_json=rule_json,
            normalized_m2_ast=normalized_m2_ast,
        )
    except (InvalidOperation, ValueError):
        observations = {
            "max_prompt_units": _lexical_unit_count(prompt),
            "max_sentence_units": _max_sentence_units(prompt),
        }

    baseline = _QUESTION_TYPE_DIFFICULTY_BASELINES.get(
        question_type if isinstance(question_type, str) else "",
        _DEFAULT_QUESTION_TYPE_DIFFICULTY_BASELINE,
    )
    features: list[dict[str, int | float | str]] = [
        _difficulty_feature("question_type_baseline", baseline, baseline)
    ]
    estimate = baseline
    prompt_units = observations["max_prompt_units"]
    prompt_contribution = _scaled_difficulty_contribution(
        prompt_units,
        scale=_PROMPT_UNITS_DIFFICULTY_SCALE,
        weight=_PROMPT_UNITS_DIFFICULTY_WEIGHT,
    )
    features.append(_difficulty_feature("prompt_units", prompt_units, prompt_contribution))
    estimate += prompt_contribution
    sentence_units = observations["max_sentence_units"]
    sentence_contribution = _scaled_difficulty_contribution(
        sentence_units,
        scale=_SENTENCE_UNITS_DIFFICULTY_SCALE,
        weight=_SENTENCE_UNITS_DIFFICULTY_WEIGHT,
    )
    features.append(_difficulty_feature("sentence_units", sentence_units, sentence_contribution))
    estimate += sentence_contribution

    maximum_numeric_value = observations.get("max_numeric_absolute_value")
    if maximum_numeric_value is not None:
        numeric_magnitude = _normalized_numeric_magnitude(maximum_numeric_value)
        numeric_contribution = numeric_magnitude * _NUMERIC_MAGNITUDE_DIFFICULTY_WEIGHT
        features.append(
            _difficulty_feature("numeric_magnitude", numeric_magnitude, numeric_contribution)
        )
        estimate += numeric_contribution

    operation_nodes = observations.get("max_math_operation_nodes")
    if operation_nodes is not None:
        operation_contribution = _scaled_difficulty_contribution(
            operation_nodes,
            scale=_M2_OPERATION_NODES_DIFFICULTY_SCALE,
            weight=_M2_OPERATION_NODES_DIFFICULTY_WEIGHT,
        )
        features.append(
            _difficulty_feature("m2_operation_nodes", operation_nodes, operation_contribution)
        )
        estimate += operation_contribution

    estimated = _quantize_bounded_difficulty(estimate, minimum=0, maximum=1)
    target = _bounded_target_difficulty(target_difficulty)
    minimum, maximum = curriculum_range
    return {
        "version": _RULE_BASED_DIFFICULTY_VERSION,
        "availability": "available",
        "reason": None,
        "target": target,
        "estimated": estimated,
        "deviation": (
            None
            if target is None
            else _quantize_bounded_difficulty(target - estimated, minimum=-1, maximum=1)
        ),
        "curriculum_range": {
            "min": _finite_signal_number(minimum),
            "max": _finite_signal_number(maximum),
        },
        "features": features,
    }


def _unavailable_difficulty_signal() -> dict[str, object]:
    """Return the versioned audit schema when evaluation cannot safely produce a signal."""

    return {
        "version": _RULE_BASED_DIFFICULTY_VERSION,
        "availability": "unavailable",
        "target": None,
        "estimated": None,
        "deviation": None,
        "curriculum_range": {"min": None, "max": None},
        "features": [],
        "reason": "validator_unavailable",
    }


def _difficulty_feature(
    feature_type: str, value: Decimal | float, contribution: float
) -> dict[str, int | float | str]:
    return {
        "type": feature_type,
        "value": _quantize_signal_number(value),
        "contribution": _quantize_signal_number(contribution),
    }


def _scaled_difficulty_contribution(value: Decimal | int, *, scale: int, weight: float) -> float:
    return min(max(float(value) / scale, 0), 1) * weight


def _normalized_numeric_magnitude(value: Decimal | int) -> float:
    if value <= 0:
        return 0.0
    order_of_magnitude = value.adjusted() + 1 if isinstance(value, Decimal) else len(str(value))
    return min(max(order_of_magnitude / _NUMERIC_MAGNITUDE_DIFFICULTY_SCALE, 0), 1)


def _finite_signal_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _bounded_target_difficulty(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    try:
        target = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not target.is_finite() or target < 0 or target > 1:
        return None
    return _finite_signal_number(target)


def _quantize_bounded_difficulty(value: object, *, minimum: float, maximum: float) -> float:
    numeric_value = _finite_signal_number(value)
    if numeric_value is None:
        return minimum
    return _quantize_signal_number(min(max(numeric_value, minimum), maximum))


def _quantize_signal_number(value: object) -> float:
    numeric_value = _finite_signal_number(value)
    if numeric_value is None:
        return 0.0
    try:
        return float(Decimal(str(numeric_value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    except InvalidOperation:
        return 0.0


def _lexical_unit_count(text: str) -> int:
    return len(_LEXICAL_UNITS.findall(unicodedata.normalize("NFC", text)))


def _max_sentence_units(text: str) -> int:
    return max(
        (_lexical_unit_count(sentence) for sentence in _SENTENCE_SEPARATORS.split(text)), default=0
    )


def _complexity_observed_value(value: Decimal | int) -> int | float:
    if isinstance(value, int):
        return value
    if value == value.to_integral_value():
        return int(value)
    observed = float(value)
    if not math.isfinite(observed):
        return int(value.to_integral_value(rounding=ROUND_CEILING))
    if Decimal(str(observed)) < value:
        return math.nextafter(observed, math.inf)
    return observed


def _m2_complexity_metrics(ast: dict[str, object]) -> tuple[Decimal | None, int]:
    maximum_numeric_value: Decimal | None = None
    operation_nodes = 0
    child_keys_by_type = {
        "add": ("args",),
        "mul": ("args",),
        "neg": ("arg",),
        "div": ("numerator", "denominator"),
        "pow": ("base", "exponent"),
        "number": (),
        "symbol": (),
    }

    stack: list[tuple[object, int]] = [(ast, 0)]
    safe_ast_nodes = 0
    while stack:
        node, depth = stack.pop()
        if depth > _M2_SAFE_AST_MAX_DEPTH:
            raise ValueError("safe MathJSON AST depth exceeds the supported limit")
        safe_ast_nodes += 1
        if safe_ast_nodes > _M2_SAFE_AST_MAX_NODES:
            raise ValueError("safe MathJSON AST node count exceeds the supported limit")
        if not isinstance(node, dict):
            raise ValueError("safe MathJSON node must be an object")
        node_type = node.get("type")
        if not isinstance(node_type, str) or node_type not in child_keys_by_type:
            raise ValueError("safe MathJSON node type is invalid")
        if set(node) != _M2_AST_FIELDS_BY_TYPE[node_type]:
            raise ValueError("safe MathJSON node fields are invalid")
        child_keys = child_keys_by_type[node_type]
        if node_type in {"add", "mul", "neg", "div", "pow"}:
            operation_nodes += 1
        if node_type == "number":
            try:
                value = _safe_ast_number_value(node["value"])
            except (InvalidOperation, ValueError) as error:
                raise ValueError("safe MathJSON number is invalid") from error
            if not value.is_finite():
                raise ValueError("safe MathJSON number is not finite")
            absolute_value = abs(value)
            if maximum_numeric_value is None or absolute_value > maximum_numeric_value:
                maximum_numeric_value = absolute_value
        if node_type == "symbol" and (not isinstance(node["name"], str) or not node["name"]):
            raise ValueError("safe MathJSON symbol is invalid")
        for child_key in child_keys:
            child = node.get(child_key)
            if child_key == "args":
                if not isinstance(child, list) or len(child) < 2:
                    raise ValueError("safe MathJSON operation arguments are invalid")
                stack.extend((argument, depth + 1) for argument in reversed(child))
            else:
                stack.append((child, depth + 1))
    return (
        None if maximum_numeric_value is None else maximum_numeric_value,
        operation_nodes,
    )


def _safe_ast_number_value(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise ValueError("safe MathJSON number value is invalid")
    value_text = str(value)
    if value_text.count("/") == 1:
        numerator_text, denominator_text = value_text.split("/", maxsplit=1)
        numerator = Decimal(numerator_text)
        denominator = Decimal(denominator_text)
        if not numerator.is_finite() or not denominator.is_finite() or denominator == 0:
            raise ValueError("safe MathJSON rational value is invalid")
        with localcontext() as context:
            context.prec = max(
                len(numerator.as_tuple().digits) + len(denominator.as_tuple().digits) + 1,
                28,
            )
            return numerator / denominator
    return Decimal(value_text)


def _m2_findings(
    rule_json: dict[str, object],
    policy_version: object,
    explanation: object,
    assertions: object,
    assertions_required: bool,
    grader_client: VerificationGraderClient,
) -> tuple[list[VerificationFinding], dict[str, object] | None]:
    if policy_version != "2":
        return [], None
    expected = rule_json["expected"]
    variables = rule_json.get("variables", [])
    try:
        normalized_m2_ast = grader_client.normalize_math_answer(
            {"mathjson": expected, "variables": variables}
        )
        _m2_complexity_metrics(normalized_m2_ast)
    except Exception:
        return (
            [
                _blocked(
                    "m2_mathjson_invalid",
                    {"probe": "expected_mathjson"},
                    "Correct the expected MathJSON expression and variables.",
                )
            ],
            None,
        )
    if assertions_required or assertions is not None:
        consistency_findings = _m2_consistency_findings(
            rule_json,
            explanation,
            assertions,
            normalized_m2_ast,
            grader_client,
        )
        if consistency_findings:
            return consistency_findings, normalized_m2_ast
    max_score = float(rule_json.get("max_score", 1))
    first_failure: str | None = None
    for probe in _m2_probes(expected):
        try:
            result = grader_client.grade(
                "M2",
                rule_json,
                {"mathjson": probe.mathjson},
                policy_version="2",
            )
            decision = result.decision
            score = result.score
            score_is_finite = (
                not isinstance(score, bool)
                and isinstance(score, int | float)
                and math.isfinite(score)
            )
            decision_matches = (
                isinstance(decision, str)
                and decision in _GRADER_DECISIONS
                and decision in probe.decisions
            )
            score_matches = score_is_finite and (
                math.isclose(score, max_score, rel_tol=0, abs_tol=1e-9)
                if probe.score_kind == "full"
                else score == 0
            )
            probe_passed = decision_matches and score_matches
        except Exception:
            probe_passed = False
        if not probe_passed and first_failure is None:
            first_failure = probe.name
    if first_failure is not None:
        return (
            [
                _blocked(
                    "m2_grader_probe_failed",
                    {"probe": first_failure},
                    "Correct the M2 rule so its answer probes match the grading policy.",
                )
            ],
            normalized_m2_ast,
        )
    return [], normalized_m2_ast


def _m2_consistency_findings(
    rule_json: dict[str, object],
    explanation: object,
    assertions: object,
    expected_ast: dict[str, object],
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    assertion_values = _assertion_values(assertions, question_type="M2")
    if isinstance(assertion_values, VerificationFinding):
        return [assertion_values]
    final_answer_text, final_answer_mathjson, declared_max_score = assertion_values
    assert final_answer_mathjson is not None
    try:
        asserted_mathjson = json.loads(final_answer_mathjson)
        asserted_ast = grader_client.normalize_math_answer(
            {"mathjson": asserted_mathjson, "variables": rule_json.get("variables", [])}
        )
        _m2_complexity_metrics(asserted_ast)
    except Exception:
        return [_unsupported_consistency_finding("M2", "final_answer_mathjson")]
    findings: list[VerificationFinding] = []
    if asserted_ast != expected_ast:
        findings.append(_answer_explanation_inconsistent_finding("M2", "final_answer_mathjson"))
    if not _has_explanation_suffix(explanation, final_answer_text):
        findings.append(_answer_explanation_inconsistent_finding("M2", "explanation_suffix"))
    maximum_score = rule_json.get("max_score", 1)
    if not _is_finite_number(maximum_score) or not math.isclose(
        declared_max_score, float(maximum_score), rel_tol=0, abs_tol=1e-9
    ):
        findings.append(_score_total_inconsistent_finding("M2"))
    return findings


def _assertion_values(
    assertions: object, *, question_type: str
) -> tuple[str, str | None, float] | VerificationFinding:
    if not isinstance(assertions, dict):
        return _unsupported_consistency_finding(question_type, "verification_assertions")
    final_answer_text = assertions.get("final_answer_text")
    final_answer_mathjson = assertions.get("final_answer_mathjson")
    declared_max_score = assertions.get("declared_max_score")
    if not isinstance(final_answer_text, str) or not final_answer_text.strip():
        return _unsupported_consistency_finding(question_type, "final_answer_text")
    if question_type == "M1" and final_answer_mathjson is not None:
        return _unsupported_consistency_finding(question_type, "final_answer_mathjson")
    if question_type == "M2" and not isinstance(final_answer_mathjson, str):
        return _unsupported_consistency_finding(question_type, "final_answer_mathjson")
    if not _is_finite_number(declared_max_score):
        return _unsupported_consistency_finding(question_type, "declared_max_score")
    return final_answer_text, final_answer_mathjson, float(declared_max_score)


def _has_explanation_suffix(explanation: object, final_answer_text: str) -> bool:
    if not isinstance(explanation, str):
        return False
    suffix = _normalize_text(f"Final answer: {final_answer_text}")
    return _normalize_text(explanation).endswith(suffix)


def _answer_explanation_inconsistent_finding(question_type: str, field: str) -> VerificationFinding:
    return _blocked(
        "answer_explanation_inconsistent",
        {"question_type": question_type, "field": field},
        "Make the structured final answer, explanation conclusion, and grading rule agree.",
    )


def _score_total_inconsistent_finding(question_type: str) -> VerificationFinding:
    return _blocked(
        "score_total_inconsistent",
        {"question_type": question_type, "field": "declared_max_score"},
        "Make the declared total score match the grading rule.",
    )


def _unsupported_consistency_finding(question_type: str, field: str) -> VerificationFinding:
    return _blocked(
        "unsupported_consistency_structure",
        {"question_type": question_type, "field": field},
        "Provide a supported structured assertion before validating this candidate.",
    )


def _m2_probes(expected: object) -> tuple[_M2Probe, ...]:
    resource_limit: object = 1
    for _ in range(21):
        resource_limit = ["Negate", resource_limit]
    return (
        _M2Probe(
            "expected_mathjson",
            expected,
            frozenset({"auto_accepted"}),
            "full",
        ),
        _M2Probe(
            "one_unit_offset",
            ["Add", expected, 1],
            frozenset({"auto_rejected", "needs_review"}),
            "zero",
        ),
        _M2Probe("empty_mathjson", None, frozenset({"needs_review"}), "zero"),
        _M2Probe(
            "zero_denominator",
            ["Divide", 1, 0],
            frozenset({"needs_review"}),
            "zero",
        ),
        _M2Probe(
            "resource_limit",
            resource_limit,
            frozenset({"needs_review"}),
            "zero",
        ),
    )


def _e1_findings(rule_json: dict[str, object]) -> list[VerificationFinding]:
    accepted_answers = rule_json.get("accepted_answers")
    if not isinstance(accepted_answers, list) or not accepted_answers:
        return [
            _blocked(
                "e1_answers_invalid",
                {"reason": "missing_answers"},
                "Provide at least one bounded accepted answer.",
            )
        ]
    normalized_answers: list[str] = []
    for answer in accepted_answers:
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 2_000:
            return [
                _blocked(
                    "e1_answers_invalid",
                    {"reason": "invalid_answer"},
                    "Provide non-empty accepted answers within the supported length.",
                )
            ]
        normalized_answers.append(_normalize_text(answer))
    if len(set(normalized_answers)) != len(normalized_answers):
        return [
            _blocked(
                "e1_answers_invalid",
                {"reason": "normalized_duplicate"},
                "Remove accepted answers that normalize to the same value.",
            )
        ]
    return []


def _e2_findings(
    rule_json: dict[str, object],
    policy_version: object,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    if policy_version != "1":
        return []
    accepted_forms = rule_json.get("accepted_forms")
    if not isinstance(accepted_forms, list) or not accepted_forms:
        return [
            _blocked(
                "e2_forms_invalid",
                {
                    "reason": "missing_forms",
                    "accepted_form_count": len(accepted_forms)
                    if isinstance(accepted_forms, list)
                    else 0,
                },
                "Provide at least one accepted form.",
            )
        ]
    normalized_forms: list[str] = []
    for form in accepted_forms:
        if not isinstance(form, str) or not form.strip() or len(form) > 2_000:
            return [
                _blocked(
                    "e2_forms_invalid",
                    {"reason": "invalid_form", "accepted_form_count": len(accepted_forms)},
                    "Provide non-empty accepted forms within the supported length.",
                )
            ]
        normalized_forms.append(_normalize_e2_form(form))
    if len(set(normalized_forms)) != len(normalized_forms):
        return [
            _blocked(
                "e2_forms_invalid",
                {
                    "reason": "normalized_duplicate",
                    "accepted_form_count": len(accepted_forms),
                },
                "Remove accepted forms that normalize to the same value.",
            )
        ]
    try:
        for form in accepted_forms:
            result = grader_client.grade(
                "E2",
                rule_json,
                {"format": "text-v1", "text": form},
                policy_version="1",
            )
            max_score = float(rule_json.get("max_score", 1))
            if result.decision != "auto_accepted" or not math.isclose(
                result.score, max_score, rel_tol=0, abs_tol=1e-9
            ):
                return [
                    _blocked(
                        "e2_grader_probe_failed",
                        {
                            "probe": "accepted_forms",
                            "accepted_form_count": len(accepted_forms),
                        },
                        "Correct the E2 forms or constraints so every form receives full credit.",
                    )
                ]
    except Exception:
        return [
            _blocked(
                "e2_grader_probe_failed",
                {
                    "probe": "accepted_forms",
                    "accepted_form_count": len(accepted_forms),
                },
                "Retry validation after the English grader is available.",
            )
        ]
    return []


def _e3_findings(
    rule_json: dict[str, object],
    policy_version: object,
    prompt: str,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    if policy_version != "1":
        return []
    accepted_answers = rule_json.get("accepted_answers", [])
    if not isinstance(accepted_answers, list) or not all(
        isinstance(answer, str) for answer in accepted_answers
    ):
        return [
            _blocked(
                "e3_grammar_probe_failed",
                {"target": "prompt", "reference_answer_count": 0},
                "Retry validation after the grammar checker is available.",
            )
        ]
    probe_rule = {**rule_json, "grammar_feedback_required": True}
    findings: list[VerificationFinding] = []
    probes = [("prompt", prompt), *(("reference_answers", answer) for answer in accepted_answers)]
    for target, text in probes:
        try:
            result = grader_client.grade(
                "E3",
                probe_rule,
                {"format": "text-v1", "text": text},
                policy_version="1",
            )
            grammar_match_count = _e3_feedback_count(result)
        except Exception:
            return [
                *findings,
                _blocked(
                    "e3_grammar_probe_failed",
                    {"target": target, "reference_answer_count": len(accepted_answers)},
                    "Retry validation after the grammar checker is available.",
                ),
            ]
        if grammar_match_count:
            findings.append(
                VerificationFinding(
                    code="e3_grammar_warning",
                    severity=ValidationFindingSeverity.WARNING,
                    evidence={
                        "target": target,
                        "grammar_match_count": grammar_match_count,
                        "reference_answer_count": len(accepted_answers),
                    },
                    remediation="Revise the generated language before teacher review.",
                )
            )
    return findings


def _e3_feedback_count(result: GradeResult) -> int:
    feedback = result.evidence.get("feedback")
    if (
        result.decision != "needs_review"
        or not isinstance(feedback, list)
        or not all(isinstance(item, dict) and item.get("type") == "grammar" for item in feedback)
    ):
        raise ValueError("unexpected E3 grammar response")
    return len(feedback)


def _e4_findings(
    rule_json: dict[str, object],
    policy_version: object,
    reading_material: object,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    if policy_version != "2":
        return []
    scoring_points = rule_json.get("scoring_points")
    if not isinstance(scoring_points, list) or not all(
        isinstance(point, dict) for point in scoring_points
    ):
        return []
    point_count = len(scoring_points)
    point_ids = [point.get("id") for point in scoring_points]
    evidence_phrases = [
        phrase
        for point in scoring_points
        for phrase in point.get("evidence_phrases", [])
        if isinstance(phrase, str)
    ]
    if not all(isinstance(point_id, str) for point_id in point_ids):
        return []
    if _has_normalized_duplicates(point_ids, normalizer=_normalize_text):
        return [
            _blocked(
                "e4_scoring_points_invalid",
                {
                    "reason": "normalized_duplicate_id",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Use distinct scoring-point identifiers.",
            )
        ]
    if any(not _normalize_e2_form(phrase) for phrase in evidence_phrases):
        return [
            _blocked(
                "e4_scoring_points_invalid",
                {
                    "reason": "normalized_empty_phrase",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Use evidence phrases that contain text after normalization.",
            )
        ]
    if _has_normalized_duplicates(evidence_phrases, normalizer=_normalize_e2_form):
        return [
            _blocked(
                "e4_scoring_points_invalid",
                {
                    "reason": "normalized_duplicate_phrase",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Use distinct evidence phrases across scoring points.",
            )
        ]
    if _has_overlapping_e4_phrases(scoring_points):
        return [
            _blocked(
                "e4_scoring_points_invalid",
                {
                    "reason": "overlapping_phrase",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Use evidence phrases that cannot award multiple scoring points.",
            )
        ]
    point_scores = [point.get("score") for point in scoring_points]
    max_score = rule_json.get("max_score", 1)
    if not all(_is_finite_number(score) for score in point_scores) or not _is_finite_number(
        max_score
    ):
        return [
            _blocked(
                "e4_score_total_invalid",
                {
                    "reason": "non_finite_score",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Provide finite scoring-point and maximum scores.",
            )
        ]
    point_score_total = sum(float(score) for score in point_scores)
    configured_max_score = float(max_score)
    if not math.isclose(point_score_total, configured_max_score, rel_tol=0, abs_tol=1e-9):
        return [
            _blocked(
                "e4_score_total_invalid",
                {
                    "scoring_point_count": point_count,
                    "point_score_total": point_score_total,
                    "max_score": configured_max_score,
                },
                "Make the scoring-point total equal the rubric maximum score.",
            )
        ]
    if not isinstance(reading_material, str) or not reading_material.strip():
        return [
            _blocked(
                "e4_reading_material_invalid",
                {
                    "reason": "missing_or_blank",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Generate a non-empty reading passage for this E4 candidate.",
            )
        ]
    if len(reading_material) > 8_000:
        return [
            _blocked(
                "e4_reading_material_invalid",
                {
                    "reason": "too_long",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Generate a reading passage within the supported length.",
            )
        ]
    normalized_material = _normalize_e2_form(reading_material)
    if any(_normalize_e2_form(phrase) not in normalized_material for phrase in evidence_phrases):
        return [
            _blocked(
                "e4_evidence_material_mismatch",
                {
                    "probe": "reading_material",
                    "scoring_point_count": point_count,
                    "evidence_phrase_count": len(evidence_phrases),
                },
                "Regenerate the candidate so each rubric phrase occurs in its reading passage.",
            )
        ]
    for point in scoring_points:
        point_score = float(point["score"])
        probe_rule = _e4_probe_rule(rule_json, point, point_score)
        for phrase in point["evidence_phrases"]:
            try:
                result = grader_client.grade(
                    "E4",
                    probe_rule,
                    {"format": "text-v1", "text": phrase},
                    policy_version="2",
                )
            except Exception:
                return [_e4_probe_failure(point_count, len(evidence_phrases))]
            if (
                result.decision != "needs_review"
                or not _is_finite_number(result.score)
                or not math.isclose(result.score, point_score, rel_tol=0, abs_tol=1e-9)
            ):
                return [_e4_probe_failure(point_count, len(evidence_phrases))]
    return []


def _e4_probe_rule(
    rule_json: dict[str, object], point: dict[str, object], point_score: float
) -> dict[str, object]:
    point_copy = {**point, "evidence_phrases": list(point["evidence_phrases"])}
    return {**rule_json, "scoring_points": [point_copy], "max_score": point_score}


def _has_normalized_duplicates(values: list[str], *, normalizer: Callable[[str], str]) -> bool:
    return len({normalizer(value) for value in values}) != len(values)


def _has_overlapping_e4_phrases(scoring_points: list[dict[str, object]]) -> bool:
    normalized_phrases: list[tuple[int, str]] = []
    for point_index, point in enumerate(scoring_points):
        for phrase in point["evidence_phrases"]:
            normalized_phrase = _normalize_e2_form(phrase)
            for other_point_index, other_phrase in normalized_phrases:
                if point_index != other_point_index and (
                    normalized_phrase in other_phrase or other_phrase in normalized_phrase
                ):
                    return True
            normalized_phrases.append((point_index, normalized_phrase))
    return False


def _e4_probe_failure(scoring_point_count: int, evidence_phrase_count: int) -> VerificationFinding:
    return _blocked(
        "e4_grader_probe_failed",
        {
            "probe": "evidence_phrases",
            "scoring_point_count": scoring_point_count,
            "evidence_phrase_count": evidence_phrase_count,
        },
        "Retry validation after the review-only grader is available.",
    )


def _persist_run(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    evaluated_revision_id: UUID,
    evaluated_revision_hash: str,
    findings: list[VerificationFinding],
    duplicate_feature_summary: dict[str, object],
    difficulty_signal: dict[str, object],
    grade_complexity_signal: dict[str, object],
    objective_prerequisite_signal: dict[str, object],
    math_semantics_signal: dict[str, object],
) -> GenerationValidationRun:
    snapshot_changed_before_lock = draft.current_revision_id != evaluated_revision_id

    session.flush()
    locked_revision = session.execute(
        select(
            GeneratedQuestionDraft.current_revision_id,
            GeneratedQuestionDraftRevision.content_hash,
        )
        .join(
            GeneratedQuestionDraftRevision,
            and_(
                GeneratedQuestionDraftRevision.id == GeneratedQuestionDraft.current_revision_id,
                GeneratedQuestionDraftRevision.generated_question_draft_id
                == GeneratedQuestionDraft.id,
            ),
        )
        .where(GeneratedQuestionDraft.id == draft.id)
        .with_for_update()
    ).one_or_none()
    current_revision = tuple(locked_revision) if locked_revision is not None else None
    evaluated_revision = (evaluated_revision_id, evaluated_revision_hash)
    if snapshot_changed_before_lock or current_revision != evaluated_revision:
        findings = [_duplicate_unavailable_finding()]
    latest_run_number = session.scalar(
        select(func.max(GenerationValidationRun.run_number)).where(
            GenerationValidationRun.generated_question_draft_id == draft.id
        )
    )
    status = _status_for(findings)
    run = GenerationValidationRun(
        generated_question_draft_id=draft.id,
        generation_job_id=draft.job_id,
        draft_revision_id=evaluated_revision_id,
        run_number=(latest_run_number or 0) + 1,
        validator_version=VALIDATOR_VERSION,
        ruleset_version=RULESET_VERSION,
        status=status,
        feature_summary_json={
            "finding_count": len(findings),
            "content_policy_version": CONTENT_POLICY_VERSION,
            "difficulty_signal": difficulty_signal,
            "grade_complexity_signal": grade_complexity_signal,
            "objective_prerequisite_signal": objective_prerequisite_signal,
            "math_semantics_signal": math_semantics_signal,
            **duplicate_feature_summary,
        },
    )
    session.add(run)
    session.flush()
    for finding in findings:
        session.add(
            ValidationFinding(
                validation_run_id=run.id,
                code=finding.code,
                severity=finding.severity,
                evidence_json=finding.evidence,
                remediation=finding.remediation,
            )
        )
    session.flush()
    return run


@dataclass(frozen=True)
class _PromptComparator:
    category: str
    prompt: str
    normalized_hash: str


@dataclass
class _DuplicateSnapshot:
    threshold: float
    candidate_fingerprints: PromptFingerprints
    exact_category: str | None
    normalized_category: str | None
    comparators: tuple[_PromptComparator, ...]
    embedding_dependency: EmbeddingDependencyVersion | None = None
    unavailable: bool = False


def _empty_duplicate_snapshot(threshold: float, prompt: str) -> _DuplicateSnapshot:
    return _DuplicateSnapshot(
        threshold=threshold,
        candidate_fingerprints=fingerprint_prompt(prompt),
        exact_category=None,
        normalized_category=None,
        comparators=(),
    )


def _validated_duplicate_threshold() -> float:
    threshold = settings.ai_duplicate_similarity_threshold
    if not _is_finite_number(threshold) or threshold < 0 or threshold > 1:
        raise ValueError("semantic similarity threshold is invalid")
    return float(threshold)


def _empty_duplicate_feature_summary(snapshot: _DuplicateSnapshot) -> dict[str, object]:
    return {
        "fingerprint_version": snapshot.candidate_fingerprints.version,
        "candidate_prompt_fingerprint": {
            "version": snapshot.candidate_fingerprints.version,
            "exact_hash": snapshot.candidate_fingerprints.exact_hash,
            "normalized_hash": snapshot.candidate_fingerprints.normalized_hash,
        },
        "similarity_threshold": snapshot.threshold,
        "comparison_counts": {"published_question": 0, "batch_candidate": 0},
        "embedding_dependency": (
            snapshot.embedding_dependency.as_dict()
            if snapshot.embedding_dependency is not None
            else None
        ),
    }


def _duplicate_feature_summary(snapshot: _DuplicateSnapshot) -> dict[str, object]:
    summary = _empty_duplicate_feature_summary(snapshot)
    summary["comparison_counts"] = {
        category: sum(comparator.category == category for comparator in snapshot.comparators)
        for category in ("published_question", "batch_candidate")
    }
    return summary


def _capture_duplicate_snapshot(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    tenant_id: object,
    prompt: str,
    threshold: float,
) -> _DuplicateSnapshot:
    try:
        fingerprints = fingerprint_prompt(prompt)
        exact_category = _fingerprint_match_category(
            session,
            draft=draft,
            tenant_id=tenant_id,
            column="exact",
            fingerprint=fingerprints.exact_hash,
        )
        normalized_category = (
            None
            if exact_category is not None
            else _fingerprint_match_category(
                session,
                draft=draft,
                tenant_id=tenant_id,
                column="normalized",
                fingerprint=fingerprints.normalized_hash,
            )
        )
        comparators = tuple(_semantic_comparators(session, draft=draft, tenant_id=tenant_id))
    except Exception:
        return _DuplicateSnapshot(
            threshold=threshold,
            candidate_fingerprints=fingerprint_prompt(prompt),
            exact_category=None,
            normalized_category=None,
            comparators=(),
            unavailable=True,
        )
    return _DuplicateSnapshot(
        threshold=threshold,
        candidate_fingerprints=fingerprints,
        exact_category=exact_category,
        normalized_category=normalized_category,
        comparators=comparators,
    )


def _duplicate_findings(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    tenant_id: object,
    prompt: str,
    grader_client: VerificationGraderClient,
    _snapshot: _DuplicateSnapshot | None = None,
) -> list[VerificationFinding]:
    snapshot = _snapshot or _capture_duplicate_snapshot(
        session,
        draft=draft,
        tenant_id=tenant_id,
        prompt=prompt,
        threshold=_validated_duplicate_threshold(),
    )
    if snapshot.unavailable:
        return [_duplicate_unavailable_finding()]
    try:
        if snapshot.exact_category is not None:
            return [
                _blocked(
                    "duplicate_exact_prompt",
                    {"comparison": snapshot.exact_category, "method": "exact_hash"},
                    _DUPLICATE_REMEDIATION,
                )
            ]

        if snapshot.normalized_category is not None:
            return [
                _blocked(
                    "duplicate_normalized_prompt",
                    {
                        "comparison": snapshot.normalized_category,
                        "method": "normalized_hash",
                    },
                    _DUPLICATE_REMEDIATION,
                )
            ]

        comparators = snapshot.comparators
        if not comparators:
            return []

        scores: list[float] = []
        embedding_dependency: EmbeddingDependencyVersion | None = None
        for offset in range(0, len(comparators), _SEMANTIC_CHUNK_SIZE):
            chunk = comparators[offset : offset + _SEMANTIC_CHUNK_SIZE]
            result = grader_client.semantic_similarity(
                prompt, [comparator.prompt for comparator in chunk]
            )
            if not isinstance(result, SemanticSimilarityResult) or not _valid_embedding_dependency(
                result.embedding
            ):
                raise ValueError("semantic similarity response metadata is invalid")
            if embedding_dependency is None:
                embedding_dependency = result.embedding
            elif result.embedding != embedding_dependency:
                raise ValueError("semantic similarity response metadata is inconsistent")
            chunk_scores = result.scores
            if not isinstance(chunk_scores, list) or len(chunk_scores) != len(chunk):
                raise ValueError("semantic similarity response count is invalid")
            if any(
                not _is_finite_number(score) or score < 0 or score > 1 for score in chunk_scores
            ):
                raise ValueError("semantic similarity response score is invalid")
            scores.extend(float(score) for score in chunk_scores)
        if len(scores) != len(comparators):
            raise ValueError("semantic similarity response coverage is incomplete")
        snapshot.embedding_dependency = embedding_dependency

        for comparator, score in zip(comparators, scores, strict=True):
            if score >= snapshot.threshold:
                return [
                    _blocked(
                        "duplicate_semantic_near_match",
                        {
                            "comparison": comparator.category,
                            "method": "semantic",
                            "threshold_band": "at_or_above",
                        },
                        _DUPLICATE_REMEDIATION,
                    )
                ]
        return []
    except Exception:
        return [_duplicate_unavailable_finding()]


def _duplicate_unavailable_finding() -> VerificationFinding:
    return _blocked(
        "duplicate_semantic_check_unavailable",
        {"category": "similarity_unavailable"},
        "Retry validation after semantic similarity is available.",
    )


def _valid_embedding_dependency(value: object) -> bool:
    return isinstance(value, EmbeddingDependencyVersion) and all(
        isinstance(item, str) and item.strip() for item in (value.id, value.revision, value.digest)
    )


def _fingerprint_match_category(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    tenant_id: object,
    column: str,
    fingerprint: str,
) -> str | None:
    published_column = (
        QuestionVersion.exact_prompt_hash
        if column == "exact"
        else QuestionVersion.normalized_prompt_hash
    )
    published_match = session.execute(
        select(published_column)
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            Question.tenant_id == tenant_id,
            QuestionVersion.status == VersionStatus.PUBLISHED,
            QuestionVersion.fingerprint_version == FINGERPRINT_VERSION,
            published_column == fingerprint,
        )
        .limit(1)
    ).first()
    if published_match is not None:
        return "published_question"

    for candidate in _batch_current_revision_candidates(session, draft=draft):
        prompt = candidate.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("batch candidate prompt is invalid")
        fingerprints = fingerprint_prompt(prompt)
        peer_fingerprint = (
            fingerprints.exact_hash if column == "exact" else fingerprints.normalized_hash
        )
        if peer_fingerprint == fingerprint:
            return "batch_candidate"
    return None


def _batch_current_revision_candidates(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
) -> list[dict[str, object]]:
    return list(
        session.scalars(
            select(GeneratedQuestionDraftRevision.candidate_json)
            .join(
                GeneratedQuestionDraft,
                and_(
                    GeneratedQuestionDraft.current_revision_id == GeneratedQuestionDraftRevision.id,
                    GeneratedQuestionDraft.id
                    == GeneratedQuestionDraftRevision.generated_question_draft_id,
                ),
            )
            .where(
                GeneratedQuestionDraft.job_id == draft.job_id,
                GeneratedQuestionDraft.id != draft.id,
            )
            .order_by(GeneratedQuestionDraft.ordinal)
        )
    )


def _semantic_comparators(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    tenant_id: object,
) -> list[_PromptComparator]:
    published_rows = session.execute(
        select(
            QuestionVersion.prompt,
            QuestionVersion.fingerprint_version,
            QuestionVersion.normalized_prompt_hash,
        )
        .join(Question, QuestionVersion.question_id == Question.id)
        .where(
            Question.tenant_id == tenant_id,
            QuestionVersion.status == VersionStatus.PUBLISHED,
        )
        .order_by(QuestionVersion.created_at)
    ).all()
    batch_rows = [
        (candidate, None, None)
        for candidate in _batch_current_revision_candidates(session, draft=draft)
    ]

    comparators: list[_PromptComparator] = []
    seen_hashes: set[str] = set()
    for category, rows in (
        ("published_question", published_rows),
        ("batch_candidate", batch_rows),
    ):
        for value, fingerprint_version, normalized_hash in rows:
            prompt = value.get("prompt") if isinstance(value, dict) else value
            if not isinstance(prompt, str) or not prompt or len(prompt) > 10_000:
                raise ValueError("semantic comparator prompt is invalid")
            deduplication_hash = (
                normalized_hash
                if fingerprint_version == FINGERPRINT_VERSION
                else fingerprint_prompt(prompt).normalized_hash
            )
            if deduplication_hash in seen_hashes:
                continue
            seen_hashes.add(deduplication_hash)
            comparators.append(
                _PromptComparator(
                    category=category,
                    prompt=prompt,
                    normalized_hash=deduplication_hash,
                )
            )
    return comparators


def _safety_findings(*texts: str) -> list[VerificationFinding]:
    return [
        VerificationFinding(
            code=match.code,
            severity=ValidationFindingSeverity(match.severity),
            evidence={
                "category": match.category,
                "rule_id": match.rule_id,
                "policy_version": CONTENT_POLICY_VERSION,
            },
            remediation=match.remediation,
        )
        for match in find_candidate_content_matches(texts)
    ]


def _text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _text_values(item)]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    return []


def _normalize_text(value: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _normalize_e2_form(value: str) -> str:
    """Mirror the E2 Grader's fixed case and terminal-punctuation normalization."""

    return _E2_TERMINAL_PUNCTUATION.sub("", _normalize_text(value)).rstrip()


def _is_finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _blocked(code: str, evidence: dict[str, object], remediation: str) -> VerificationFinding:
    return VerificationFinding(
        code=code,
        severity=ValidationFindingSeverity.BLOCKED,
        evidence=evidence,
        remediation=remediation,
    )


def _status_for(findings: list[VerificationFinding]) -> ValidationRunStatus:
    if any(finding.severity is ValidationFindingSeverity.BLOCKED for finding in findings):
        return ValidationRunStatus.BLOCKED
    if findings:
        return ValidationRunStatus.WARNING
    return ValidationRunStatus.PASSED
