"""Fail-fast candidate verification wrapper with de-identified capacity evidence."""

from __future__ import annotations

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
from .verification_budget import (
    VerificationBudget,
    VerificationBudgetExceeded,
    VerificationDependencyTimeout,
)
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
    budget: VerificationBudget | None = None,
    persistence_finalizer: verification.VerificationPersistenceFinalizer | None = None,
) -> GenerationValidationRun:
    """Reject over-capacity candidates before recursive or external work."""

    if revision.generated_question_draft_id != draft.id:
        raise ValueError("candidate revision does not belong to the draft")

    if budget is not None:
        budget.check("capacity_preflight")

    try:
        capacity = evaluate_verification_capacity(revision.candidate_json)
    except (VerificationBudgetExceeded, VerificationDependencyTimeout):
        raise
    except Exception:
        if budget is not None:
            budget.check("capacity_preflight")
        return _persist_capacity_failure(
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
            budget=budget,
            persistence_finalizer=persistence_finalizer,
        )

    if budget is not None:
        budget.check("capacity_preflight")

    capacity_signal = capacity.feature_summary()
    finalizer = _capacity_persistence_finalizer(
        capacity_signal,
        persistence_finalizer,
    )
    if not capacity.blocked:
        return verification.run_candidate_verification(
            session,
            draft=draft,
            revision=revision,
            grader_client=grader_client,
            budget=budget,
            persistence_finalizer=finalizer,
        )

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
        budget=budget,
        persistence_finalizer=persistence_finalizer,
    )


def _persist_capacity_failure(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    findings: list[verification.VerificationFinding],
    signal: dict[str, object],
    reason: str,
    budget: VerificationBudget | None = None,
    persistence_finalizer: verification.VerificationPersistenceFinalizer | None = None,
) -> GenerationValidationRun:
    return verification._persist_run(
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
        budget=budget,
        persistence_finalizer=_capacity_persistence_finalizer(
            signal,
            persistence_finalizer,
        ),
    )


def _capacity_persistence_finalizer(
    signal: dict[str, object],
    downstream: verification.VerificationPersistenceFinalizer | None = None,
) -> verification.VerificationPersistenceFinalizer:
    def finalize(
        plan: verification.VerificationPersistencePlan,
    ) -> verification.VerificationPersistencePlan:
        enriched = verification.VerificationPersistencePlan(
            findings=plan.findings,
            validator_version=CAPACITY_AWARE_VALIDATOR_VERSION,
            ruleset_version=CAPACITY_AWARE_RULESET_VERSION,
            feature_summary_extensions={
                **plan.feature_summary_extensions,
                "verification_capacity_signal": signal,
            },
        )
        return downstream(enriched) if downstream is not None else enriched

    return finalize


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
