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
from .verification_capacity import evaluate_verification_capacity


def run_capacity_aware_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    grader_client: verification.VerificationGraderClient,
) -> GenerationValidationRun:
    """Reject over-capacity candidates before any external dependency call."""

    capacity = evaluate_verification_capacity(revision.candidate_json)
    capacity_signal = capacity.feature_summary()
    if not capacity.blocked:
        run = verification.run_candidate_verification(
            session,
            draft=draft,
            revision=revision,
            grader_client=grader_client,
        )
        _attach_capacity_signal(session, run=run, signal=capacity_signal)
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
    run = verification._persist_run(
        session,
        draft=draft,
        evaluated_revision_id=revision.id,
        evaluated_revision_hash=revision.content_hash,
        findings=findings,
        duplicate_feature_summary=_capacity_blocked_duplicate_summary(),
        difficulty_signal=verification._unavailable_difficulty_signal(),
        grade_complexity_signal=unavailable_grade_complexity_signal(
            "capacity_preflight_blocked"
        ),
        objective_prerequisite_signal=unavailable_objective_prerequisite_signal(
            "capacity_preflight_blocked"
        ),
        math_semantics_signal=unavailable_math_semantics_signal(
            "capacity_preflight_blocked"
        ),
    )
    _attach_capacity_signal(session, run=run, signal=capacity_signal)
    return run


def _attach_capacity_signal(
    session: Session,
    *,
    run: GenerationValidationRun,
    signal: dict[str, object],
) -> None:
    summary = dict(run.feature_summary_json)
    summary["verification_capacity_signal"] = signal
    run.feature_summary_json = cast(dict[str, object], summary)
    session.flush()


def _capacity_blocked_duplicate_summary() -> dict[str, object]:
    return {
        "fingerprint_version": None,
        "candidate_prompt_fingerprint": None,
        "similarity_threshold": None,
        "comparison_counts": {
            "published_question": 0,
            "batch_candidate": 0,
        },
        "embedding_dependency": None,
    }
