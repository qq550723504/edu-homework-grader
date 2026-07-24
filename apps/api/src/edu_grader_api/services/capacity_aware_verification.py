"""Fail-fast candidate verification wrapper with de-identified capacity evidence."""

from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationValidationRun,
    ValidationFindingSeverity,
)
from . import question_verification as verification
from .grade_complexity import unavailable_grade_complexity_signal
from .math_semantics import unavailable_math_semantics_signal
from .objective_prerequisites import unavailable_objective_prerequisite_signal
from .verification_capacity import (
    evaluate_verification_capacity,
    unavailable_verification_capacity_signal,
)

CAPACITY_AWARE_VALIDATOR_VERSION = "verification-v9"
CAPACITY_AWARE_RULESET_VERSION = "rules-v9"


def run_capacity_aware_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    grader_client: verification.VerificationGraderClient,
) -> GenerationValidationRun:
    """Reject over-capacity candidates before recursive or external work."""

    if revision.generated_question_draft_id != draft.id:
        raise ValueError("candidate revision does not belong to the draft")

    try:
        capacity = evaluate_verification_capacity(revision.candidate_json)
    except Exception:
        run = _persist_capacity_failure(
            session,
            draft=draft,
            revision=revision,
            findings=[
                verification.VerificationFinding(
                    code="validator_unavailable",
                    severity=ValidationFindingSeverity.BLOCKED,
                    evidence={"category": "capacity_preflight_unavailable"},
                    remediation=(
                        "Retry validation. If the problem continues, contact an administrator."
                    ),
                )
            ],
            signal=unavailable_verification_capacity_signal("capacity_preflight_unavailable"),
            reason="capacity_preflight_unavailable",
        )
        return run

    capacity_signal = capacity.feature_summary()
    if not capacity.blocked:
        run = verification.run_candidate_verification(
            session,
            draft=draft,
            revision=revision,
            grader_client=grader_client,
        )
        _finalize_capacity_evidence(session, run=run, signal=capacity_signal)
        return run

    findings = [
        verification.VerificationFinding(
            code=finding.code,
            severity=ValidationFindingSeverity.BLOCKED,
            evidence=finding.evidence,
            remediation=finding.remediation,
        )
        for finding in capacity.findings
    ]
    return _persist_capacity_failure(
        session,
        draft=draft,
        revision=revision,
        findings=findings,
        signal=capacity_signal,
        reason="capacity_preflight_blocked",
    )


def _persist_capacity_failure(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    findings: list[verification.VerificationFinding],
    signal: dict[str, object],
    reason: str,
) -> GenerationValidationRun:
    run = verification._persist_run(
        session,
        draft=draft,
        evaluated_revision_id=revision.id,
        evaluated_revision_hash=revision.content_hash,
        findings=findings,
        duplicate_feature_summary=_capacity_blocked_duplicate_summary(reason),
        difficulty_signal=verification._unavailable_difficulty_signal(),
        grade_complexity_signal=unavailable_grade_complexity_signal(reason),
        objective_prerequisite_signal=unavailable_objective_prerequisite_signal(reason),
        math_semantics_signal=unavailable_math_semantics_signal(reason),
    )
    _finalize_capacity_evidence(session, run=run, signal=signal)
    return run


def _finalize_capacity_evidence(
    session: Session,
    *,
    run: GenerationValidationRun,
    signal: dict[str, object],
) -> None:
    summary = dict(run.feature_summary_json)
    summary["verification_capacity_signal"] = signal
    run.feature_summary_json = cast(dict[str, object], summary)
    run.validator_version = CAPACITY_AWARE_VALIDATOR_VERSION
    run.ruleset_version = CAPACITY_AWARE_RULESET_VERSION
    session.flush()


def _capacity_blocked_duplicate_summary(reason: str) -> dict[str, object]:
    return {
        "fingerprint_version": None,
        "candidate_prompt_fingerprint": None,
        "similarity_threshold": None,
        "comparison_counts": {
            "published_question": 0,
            "batch_candidate": 0,
        },
        "embedding_dependency": None,
        "duplicate_check_availability": "unavailable",
        "duplicate_check_reason": reason,
    }
