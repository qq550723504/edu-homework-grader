"""Deterministic verification for AI-generated candidate-question drafts."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Callable, Protocol
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    GeneratedQuestionDraft,
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
from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .question_fingerprints import FINGERPRINT_VERSION, PromptFingerprints, fingerprint_prompt
from .questions import GradeResult


VALIDATOR_VERSION = "verification-v3"
RULESET_VERSION = "rules-v3"
_SEMANTIC_CHUNK_SIZE = 128
_DUPLICATE_REMEDIATION = "Revise the prompt to make the candidate meaningfully distinct."
_WHITESPACE = re.compile(r"\s+")
_E2_TERMINAL_PUNCTUATION = re.compile(r"[.!?。！？]+$")
_UNSAFE_MINOR_TERMS = (
    ("pornographic", "adult_content"),
    ("sexual content", "adult_content"),
    ("self-harm instructions", "self_harm"),
    ("graphic violence", "graphic_violence"),
)
_GRADE_TEXT_LIMITS = {
    "G1": 300,
    "G2": 400,
    "G3": 500,
    "G4": 600,
    "G5": 700,
    "G6": 800,
    "G7": 1_000,
    "G8": 1_100,
    "G9": 1_200,
    "G10": 1_400,
    "G11": 1_600,
    "G12": 1_800,
}


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
    evaluated_candidate_fingerprints: PromptFingerprints


def run_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    grader_client: VerificationGraderClient,
) -> GenerationValidationRun:
    """Evaluate a candidate and append a new, immutable verification result."""

    duplicate_threshold = _validated_duplicate_threshold()
    prompt = draft.candidate_json.get("prompt")
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
            evaluated_candidate_fingerprints=duplicate_snapshot.candidate_fingerprints,
        )
    return _persist_run(
        session,
        draft=draft,
        findings=evaluation.findings,
        duplicate_feature_summary=evaluation.duplicate_feature_summary,
        evaluated_candidate_fingerprints=evaluation.evaluated_candidate_fingerprints,
    )


def _evaluate_candidate(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    grader_client: VerificationGraderClient,
    duplicate_snapshot: _DuplicateSnapshot,
) -> _CandidateEvaluation:
    job = session.get(GenerationJob, draft.job_id)
    if job is None:
        raise ValueError("candidate generation job was not found")
    revision = job.curriculum_objective_revision
    candidate = draft.candidate_json
    findings: list[VerificationFinding] = []

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
        grade_limit = _GRADE_TEXT_LIMITS.get(revision.objective.grade_mapping.internal_level)
        if grade_limit is not None and len(prompt) > grade_limit:
            findings.append(
                VerificationFinding(
                    code="grade_text_complexity_warning",
                    severity=ValidationFindingSeverity.WARNING,
                    evidence={"grade_level": revision.objective.grade_mapping.internal_level},
                    remediation="Shorten the prompt for the selected grade level.",
                )
            )

    if question_type == "M1" and isinstance(rule_json, dict):
        findings.extend(_m1_findings(rule_json, policy_version, grader_client))
    if question_type == "M2" and isinstance(rule_json, dict) and not policy_errors:
        findings.extend(_m2_findings(rule_json, policy_version, grader_client))
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
        evaluated_candidate_fingerprints=duplicate_snapshot.candidate_fingerprints,
    )


def _m1_findings(
    rule_json: dict[str, object],
    policy_version: object,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
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
    try:
        result = grader_client.grade(
            "M1",
            rule_json,
            {"format": "text-v1", "text": str(expected)},
            policy_version=policy_version if isinstance(policy_version, str) else None,
        )
    except Exception:
        return [
            _blocked(
                "m1_grader_probe_failed",
                {"probe": "expected_answer"},
                "Retry validation after the numeric grader is available.",
            )
        ]
    if result.decision != "auto_accepted" or result.score <= 0:
        return [
            _blocked(
                "m1_grader_probe_failed",
                {"probe": "expected_answer"},
                "Correct the numeric rule so its expected answer is accepted by the grader.",
            )
        ]
    return []


def _m2_findings(
    rule_json: dict[str, object],
    policy_version: object,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
    if policy_version != "2":
        return []
    expected = rule_json["expected"]
    variables = rule_json.get("variables", [])
    try:
        grader_client.normalize_math_answer({"mathjson": expected, "variables": variables})
    except Exception:
        return [
            _blocked(
                "m2_mathjson_invalid",
                {"probe": "expected_mathjson"},
                "Correct the expected MathJSON expression and variables.",
            )
        ]
    try:
        result = grader_client.grade(
            "M2",
            rule_json,
            {"mathjson": expected},
            policy_version="2",
        )
    except Exception:
        return [
            _blocked(
                "m2_grader_probe_failed",
                {"probe": "expected_mathjson"},
                "Retry validation after the expression grader is available.",
            )
        ]
    max_score = float(rule_json.get("max_score", 1))
    if result.decision != "auto_accepted" or not math.isclose(
        result.score, max_score, rel_tol=0, abs_tol=1e-9
    ):
        return [
            _blocked(
                "m2_grader_probe_failed",
                {"probe": "expected_mathjson"},
                "Correct the M2 rule so the expected expression receives full credit.",
            )
        ]
    return []


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
    findings: list[VerificationFinding],
    duplicate_feature_summary: dict[str, object],
    evaluated_candidate_fingerprints: PromptFingerprints,
) -> GenerationValidationRun:
    evaluated_fingerprints = (
        evaluated_candidate_fingerprints.version,
        evaluated_candidate_fingerprints.exact_hash,
        evaluated_candidate_fingerprints.normalized_hash,
    )
    in_memory_fingerprints = (
        draft.fingerprint_version,
        draft.exact_prompt_hash,
        draft.normalized_prompt_hash,
    )
    snapshot_changed_before_lock = in_memory_fingerprints != evaluated_fingerprints

    session.flush()
    locked_fingerprints = session.execute(
        select(
            GeneratedQuestionDraft.fingerprint_version,
            GeneratedQuestionDraft.exact_prompt_hash,
            GeneratedQuestionDraft.normalized_prompt_hash,
        )
        .where(GeneratedQuestionDraft.id == draft.id)
        .with_for_update()
    ).one_or_none()
    current_fingerprints = tuple(locked_fingerprints) if locked_fingerprints is not None else None
    if snapshot_changed_before_lock or current_fingerprints != evaluated_fingerprints:
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
        run_number=(latest_run_number or 0) + 1,
        validator_version=VALIDATOR_VERSION,
        ruleset_version=RULESET_VERSION,
        status=status,
        feature_summary_json={
            "finding_count": len(findings),
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

    batch_column = (
        GeneratedQuestionDraft.exact_prompt_hash
        if column == "exact"
        else GeneratedQuestionDraft.normalized_prompt_hash
    )
    batch_match = session.execute(
        select(batch_column)
        .where(
            GeneratedQuestionDraft.job_id == draft.job_id,
            GeneratedQuestionDraft.id != draft.id,
            GeneratedQuestionDraft.fingerprint_version == FINGERPRINT_VERSION,
            batch_column == fingerprint,
        )
        .limit(1)
    ).first()
    return "batch_candidate" if batch_match is not None else None


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
    batch_rows = session.execute(
        select(
            GeneratedQuestionDraft.candidate_json,
            GeneratedQuestionDraft.fingerprint_version,
            GeneratedQuestionDraft.normalized_prompt_hash,
        )
        .where(
            GeneratedQuestionDraft.job_id == draft.job_id,
            GeneratedQuestionDraft.id != draft.id,
        )
        .order_by(GeneratedQuestionDraft.ordinal)
    ).all()

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
    normalized_content = _normalize_text(" ".join(texts))
    for term, category in _UNSAFE_MINOR_TERMS:
        if term in normalized_content:
            return [
                _blocked(
                    "unsafe_minor_content",
                    {"category": category},
                    "Remove unsafe content before asking for teacher review.",
                )
            ]
    return []


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
    return not isinstance(value, bool) and isinstance(value, int | float) and math.isfinite(value)


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
