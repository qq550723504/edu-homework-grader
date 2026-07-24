"""Production verification wrapper with a shared monotonic timeout budget."""

from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from sqlalchemy.orm import Session

from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationValidationRun,
    ValidationFinding,
    ValidationFindingSeverity,
    ValidationRunStatus,
)
from ..settings import settings
from . import question_verification as core
from .capacity_aware_verification import run_capacity_aware_candidate_verification
from .grade_complexity import unavailable_grade_complexity_signal
from .math_semantics import unavailable_math_semantics_signal
from .objective_prerequisites import unavailable_objective_prerequisite_signal
from .verification_budget import (
    VERIFICATION_BUDGET_RULESET_VERSION,
    BudgetedGraderClient,
    BudgetStage,
    DependencyKind,
    VerificationBudget,
    VerificationBudgetExceeded,
    VerificationDependencyTimeout,
)
from .verification_capacity import unavailable_verification_capacity_signal

BUDGET_AWARE_VALIDATOR_VERSION = "verification-v10"
BUDGET_AWARE_RULESET_VERSION = "rules-v10"


def run_budget_aware_candidate_verification(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    grader_client: core.VerificationGraderClient,
    clock: Callable[[], float] = monotonic,
) -> GenerationValidationRun:
    """Run production validation under one terminal monotonic budget."""

    if revision.generated_question_draft_id != draft.id:
        raise ValueError("candidate revision does not belong to the draft")

    budget = VerificationBudget(
        total_seconds=settings.verification_total_timeout_seconds,
        clock=clock,
    )
    budgeted_client = BudgetedGraderClient(grader_client, budget)
    try:
        budget.check("capacity_preflight")
        run = run_capacity_aware_candidate_verification(
            session,
            draft=draft,
            revision=revision,
            grader_client=budgeted_client,
        )
    except VerificationBudgetExceeded as error:
        return _persist_terminal_failure(
            session,
            draft=draft,
            revision=revision,
            budget=budget,
            finding=_total_timeout_finding(error.stage, budget.total_seconds),
        )
    except VerificationDependencyTimeout as error:
        return _persist_terminal_failure(
            session,
            draft=draft,
            revision=revision,
            budget=budget,
            finding=_dependency_timeout_finding(error.dependency),
        )

    if budget.status == "active":
        try:
            budget.check("persist")
        except VerificationBudgetExceeded:
            pass
    if budget.status == "active":
        budget.mark_completed()

    terminal_finding = _finding_for_terminal_budget(budget)
    return _finalize_run(
        session,
        run=run,
        budget=budget,
        terminal_finding=terminal_finding,
    )


def _persist_terminal_failure(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    revision: GeneratedQuestionDraftRevision,
    budget: VerificationBudget,
    finding: core.VerificationFinding,
) -> GenerationValidationRun:
    run = core._persist_run(
        session,
        draft=draft,
        evaluated_revision_id=revision.id,
        evaluated_revision_hash=revision.content_hash,
        findings=[finding],
        duplicate_feature_summary=core._unavailable_duplicate_feature_summary(
            "verification_timeout"
        ),
        difficulty_signal=core._unavailable_difficulty_signal(),
        grade_complexity_signal=unavailable_grade_complexity_signal(
            "verification_timeout"
        ),
        objective_prerequisite_signal=unavailable_objective_prerequisite_signal(
            "verification_timeout"
        ),
        math_semantics_signal=unavailable_math_semantics_signal("verification_timeout"),
    )
    run.status = ValidationRunStatus.BLOCKED
    summary = dict(run.feature_summary_json)
    summary["verification_capacity_signal"] = unavailable_verification_capacity_signal(
        "verification_timeout"
    )
    run.feature_summary_json = summary
    return _finalize_run(session, run=run, budget=budget, terminal_finding=None)


def _finalize_run(
    session: Session,
    *,
    run: GenerationValidationRun,
    budget: VerificationBudget,
    terminal_finding: core.VerificationFinding | None,
) -> GenerationValidationRun:
    added_terminal_finding = False
    if terminal_finding is not None and not any(
        finding.code == terminal_finding.code for finding in run.findings
    ):
        session.add(
            ValidationFinding(
                validation_run_id=run.id,
                code=terminal_finding.code,
                severity=terminal_finding.severity,
                evidence_json=terminal_finding.evidence,
                remediation=terminal_finding.remediation,
            )
        )
        added_terminal_finding = True
    if terminal_finding is not None:
        run.status = ValidationRunStatus.BLOCKED

    summary = dict(run.feature_summary_json)
    summary["verification_budget_signal"] = budget.feature_summary()
    if added_terminal_finding:
        summary["finding_count"] = int(summary.get("finding_count", 0)) + 1
    run.feature_summary_json = summary
    run.validator_version = BUDGET_AWARE_VALIDATOR_VERSION
    run.ruleset_version = BUDGET_AWARE_RULESET_VERSION
    session.flush()
    return run


def _finding_for_terminal_budget(
    budget: VerificationBudget,
) -> core.VerificationFinding | None:
    signal = budget.feature_summary()
    if budget.status == "total_timeout":
        stage = signal.get("terminal_stage")
        return _total_timeout_finding(
            stage if isinstance(stage, str) else "persist",
            budget.total_seconds,
        )
    if budget.status == "dependency_timeout":
        dependency = signal.get("terminal_dependency")
        if dependency in {"normalizer", "grader", "language", "similarity"}:
            return _dependency_timeout_finding(dependency)
    return None


def _total_timeout_finding(
    stage: BudgetStage | str, total_budget_seconds: float
) -> core.VerificationFinding:
    return core.VerificationFinding(
        code="verification_total_timeout",
        severity=ValidationFindingSeverity.BLOCKED,
        evidence={
            "ruleset_version": VERIFICATION_BUDGET_RULESET_VERSION,
            "stage": stage,
            "total_budget_seconds": total_budget_seconds,
        },
        remediation="Retry validation after reducing load or restoring validation capacity.",
    )


def _dependency_timeout_finding(
    dependency: DependencyKind,
) -> core.VerificationFinding:
    code = {
        "normalizer": "normalizer_timeout",
        "grader": "grader_timeout",
        "language": "language_timeout",
        "similarity": "similarity_timeout",
    }[dependency]
    return core.VerificationFinding(
        code=code,
        severity=ValidationFindingSeverity.BLOCKED,
        evidence={
            "ruleset_version": VERIFICATION_BUDGET_RULESET_VERSION,
            "dependency": dependency,
        },
        remediation="Retry validation after the required validation dependency is available.",
    )
