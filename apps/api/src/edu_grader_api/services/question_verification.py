"""Deterministic verification for AI-generated candidate-question drafts."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Protocol
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    GeneratedQuestionDraft,
    GenerationJob,
    GenerationValidationRun,
    ValidationFinding,
    ValidationFindingSeverity,
    ValidationRunStatus,
)
from ..policies import validate_policy
from .questions import GradeResult


VALIDATOR_VERSION = "verification-v1"
RULESET_VERSION = "rules-v1"
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


@dataclass(frozen=True)
class VerificationFinding:
    code: str
    severity: ValidationFindingSeverity
    evidence: dict[str, object]
    remediation: str


def run_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    grader_client: VerificationGraderClient,
) -> GenerationValidationRun:
    """Evaluate a candidate and append a new, immutable verification result."""

    try:
        findings = _evaluate_candidate(session, draft=draft, grader_client=grader_client)
    except Exception:
        findings = [
            VerificationFinding(
                code="validator_unavailable",
                severity=ValidationFindingSeverity.BLOCKED,
                evidence={"category": "internal_validation_error"},
                remediation="Retry validation. If the problem continues, contact an administrator.",
            )
        ]
    return _persist_run(session, draft=draft, findings=findings)


def _evaluate_candidate(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    grader_client: VerificationGraderClient,
) -> list[VerificationFinding]:
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
            *(_text_values(rule_json) if isinstance(rule_json, dict) else []),
        )
    )
    if isinstance(prompt, str):
        if _has_normalized_duplicate(session, draft=draft, tenant_id=job.tenant_id, prompt=prompt):
            findings.append(
                VerificationFinding(
                    code="duplicate_candidate_content",
                    severity=ValidationFindingSeverity.WARNING,
                    evidence={"comparison": "normalized_prompt"},
                    remediation="Revise the prompt to make the candidate meaningfully distinct.",
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
    if question_type == "E1" and isinstance(rule_json, dict):
        findings.extend(_e1_findings(rule_json))
    return findings


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


def _persist_run(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    findings: list[VerificationFinding],
) -> GenerationValidationRun:
    session.execute(
        select(GeneratedQuestionDraft)
        .where(GeneratedQuestionDraft.id == draft.id)
        .with_for_update()
    )
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
        feature_summary_json={"finding_count": len(findings)},
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


def _has_normalized_duplicate(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    tenant_id: object,
    prompt: str,
) -> bool:
    normalized_prompt = _normalize_text(prompt)
    other_drafts = session.scalars(
        select(GeneratedQuestionDraft)
        .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
        .where(GenerationJob.tenant_id == tenant_id, GeneratedQuestionDraft.id != draft.id)
    )
    return any(
        isinstance(other_prompt := other.candidate_json.get("prompt"), str)
        and _normalize_text(other_prompt) == normalized_prompt
        for other in other_drafts
    )


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
