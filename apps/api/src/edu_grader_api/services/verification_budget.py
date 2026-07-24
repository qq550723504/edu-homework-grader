"""Versioned monotonic budget primitives for candidate verification."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Literal, Protocol

from .grader import (
    GraderRequestTimeoutError,
    SemanticSimilarityResult,
)
from .questions import GradeResult

VERIFICATION_BUDGET_RULESET_VERSION = "verification-budget-v1"

BudgetStage = Literal[
    "capacity_preflight",
    "duplicate_check",
    "normalizer",
    "grader",
    "language",
    "similarity",
    "persist",
]
DependencyKind = Literal["normalizer", "grader", "language", "similarity"]
BudgetStatus = Literal["active", "completed", "total_timeout", "dependency_timeout"]


class VerificationBudgetExceeded(TimeoutError):
    """Raised when the shared candidate-verification budget is exhausted."""

    def __init__(self, stage: BudgetStage) -> None:
        self.stage = stage
        super().__init__(f"verification budget exhausted before {stage}")


class VerificationDependencyTimeout(TimeoutError):
    """Stable timeout classification without URLs, payloads, or provider diagnostics."""

    def __init__(self, dependency: DependencyKind) -> None:
        self.dependency = dependency
        super().__init__(f"verification dependency timed out: {dependency}")


class BudgetedGraderDelegate(Protocol):
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


@dataclass(slots=True)
class VerificationBudget:
    """A shared monotonic deadline with de-identified status evidence."""

    total_seconds: float
    clock: Callable[[], float] = monotonic
    _started_at: float = field(init=False, repr=False)
    _status: BudgetStatus = field(init=False, default="active", repr=False)
    _terminal_stage: BudgetStage | None = field(init=False, default=None, repr=False)
    _terminal_dependency: DependencyKind | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.total_seconds, bool)
            or not isinstance(self.total_seconds, int | float)
            or not math.isfinite(float(self.total_seconds))
            or self.total_seconds <= 0
        ):
            raise ValueError("verification total budget must be a positive finite number")
        started_at = self.clock()
        if not math.isfinite(started_at):
            raise ValueError("verification budget clock must return a finite value")
        self.total_seconds = float(self.total_seconds)
        self._started_at = started_at

    @property
    def status(self) -> BudgetStatus:
        return self._status

    @property
    def terminal(self) -> bool:
        return self._status in {"total_timeout", "dependency_timeout"}

    def remaining_seconds(self, stage: BudgetStage) -> float:
        """Return remaining budget or raise a stable terminal timeout."""

        self._raise_terminal()
        now = self.clock()
        if not math.isfinite(now):
            self._mark_total_timeout(stage)
            raise VerificationBudgetExceeded(stage)
        remaining = self.total_seconds - max(0.0, now - self._started_at)
        if remaining <= 0:
            self._mark_total_timeout(stage)
            raise VerificationBudgetExceeded(stage)
        return remaining

    def check(self, stage: BudgetStage) -> None:
        self.remaining_seconds(stage)

    def mark_completed(self) -> None:
        if not self.terminal:
            self._status = "completed"

    def mark_dependency_timeout(self, dependency: DependencyKind) -> None:
        if not self.terminal:
            self._status = "dependency_timeout"
            self._terminal_dependency = dependency

    def feature_summary(self) -> dict[str, object]:
        """Return only versioned configuration and stable terminal classification."""

        return {
            "availability": "available",
            "version": VERIFICATION_BUDGET_RULESET_VERSION,
            "total_budget_seconds": self.total_seconds,
            "status": self._status,
            "terminal_stage": self._terminal_stage,
            "terminal_dependency": self._terminal_dependency,
        }

    def _mark_total_timeout(self, stage: BudgetStage) -> None:
        if not self.terminal:
            self._status = "total_timeout"
            self._terminal_stage = stage

    def _raise_terminal(self) -> None:
        if self._status == "total_timeout" and self._terminal_stage is not None:
            raise VerificationBudgetExceeded(self._terminal_stage)
        if self._status == "dependency_timeout" and self._terminal_dependency is not None:
            raise VerificationDependencyTimeout(self._terminal_dependency)


class BudgetedGraderClient:
    """Prevent new dependency calls after total or dependency timeout."""

    def __init__(self, delegate: BudgetedGraderDelegate, budget: VerificationBudget) -> None:
        self._delegate = delegate
        self._budget = budget

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return self._invoke(
            stage="normalizer",
            dependency="normalizer",
            callback=lambda: self._delegate.normalize_math_answer(answer_json),
        )

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return self._invoke(
            stage="grader",
            dependency="grader",
            callback=lambda: self._delegate.grade(
                question_type,
                rule_json,
                answer_json,
                policy_version=policy_version,
            ),
        )

    def semantic_similarity(
        self, query: str, comparisons: list[str]
    ) -> SemanticSimilarityResult:
        return self._invoke(
            stage="similarity",
            dependency="similarity",
            callback=lambda: self._delegate.semantic_similarity(query, comparisons),
        )

    def _invoke[Result](
        self,
        *,
        stage: BudgetStage,
        dependency: DependencyKind,
        callback: Callable[[], Result],
    ) -> Result:
        self._budget.check(stage)
        try:
            result = callback()
        except GraderRequestTimeoutError as error:
            classified = _dependency_for_operation(error.operation, fallback=dependency)
            self._budget.mark_dependency_timeout(classified)
            raise VerificationDependencyTimeout(classified) from error
        self._budget.check(stage)
        return result


def _dependency_for_operation(
    operation: str, *, fallback: DependencyKind
) -> DependencyKind:
    return {
        "normalizer": "normalizer",
        "grade": "grader",
        "similarity": "similarity",
        "language": "language",
    }.get(operation, fallback)
