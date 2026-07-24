from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from edu_grader_api.services.grader import (
    EmbeddingDependencyVersion,
    GraderRequestTimeoutError,
    SemanticSimilarityResult,
)
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.services.verification_budget import (
    VERIFICATION_BUDGET_RULESET_VERSION,
    BudgetedGraderClient,
    VerificationBudget,
    VerificationBudgetExceeded,
    VerificationDependencyTimeout,
)


@dataclass
class FakeClock:
    current: float = 100.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class PassingDelegate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.calls.append("normalizer")
        return {"type": "number", "value": "4"}

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.calls.append("grader")
        return GradeResult(
            decision="auto_accepted",
            score=1,
            evidence={},
            grader_version="test-grader-v1",
        )

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        self.calls.append("similarity")
        return SemanticSimilarityResult(
            scores=[0.1 for _ in comparisons],
            embedding=EmbeddingDependencyVersion(
                id="test-model",
                revision="revision",
                digest="sha256:digest",
            ),
        )


class TimeoutDelegate(PassingDelegate):
    def __init__(self, operation: str) -> None:
        super().__init__()
        self.operation = operation

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.calls.append("normalizer")
        raise GraderRequestTimeoutError(self.operation)

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.calls.append("grader")
        raise GraderRequestTimeoutError(self.operation)

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        self.calls.append("similarity")
        raise GraderRequestTimeoutError(self.operation)


def test_budget_uses_monotonic_deadline_without_elapsed_evidence() -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=30, clock=clock)

    clock.advance(29.5)

    assert budget.remaining_seconds("grader") == pytest.approx(0.5)
    signal = budget.feature_summary()
    assert signal == {
        "availability": "available",
        "version": VERIFICATION_BUDGET_RULESET_VERSION,
        "total_budget_seconds": 30.0,
        "status": "active",
        "terminal_stage": None,
        "terminal_dependency": None,
    }
    assert "elapsed" not in signal
    assert "started" not in signal


def test_budget_expires_exactly_at_deadline_and_remains_terminal() -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=10, clock=clock)
    clock.advance(10)

    with pytest.raises(VerificationBudgetExceeded) as first:
        budget.check("duplicate_check")
    with pytest.raises(VerificationBudgetExceeded) as second:
        budget.check("grader")

    assert first.value.stage == "duplicate_check"
    assert second.value.stage == "duplicate_check"
    assert budget.feature_summary() == {
        "availability": "available",
        "version": VERIFICATION_BUDGET_RULESET_VERSION,
        "total_budget_seconds": 10.0,
        "status": "total_timeout",
        "terminal_stage": "duplicate_check",
        "terminal_dependency": None,
    }


def test_invalid_budget_configuration_is_rejected() -> None:
    for value in (0, -1, float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            VerificationBudget(total_seconds=value)  # type: ignore[arg-type]


def test_budgeted_client_checks_before_and_after_each_call() -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=2, clock=clock)
    delegate = PassingDelegate()
    client = BudgetedGraderClient(delegate, budget)

    original_grade = delegate.grade

    def slow_grade(
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        result = original_grade(
            question_type,
            rule_json,
            answer_json,
            policy_version=policy_version,
        )
        clock.advance(2)
        return result

    delegate.grade = slow_grade  # type: ignore[method-assign]

    with pytest.raises(VerificationBudgetExceeded) as raised:
        client.grade("M1", {"expected": 4}, {"format": "text-v1", "text": "4"})

    assert raised.value.stage == "grader"
    assert delegate.calls == ["grader"]
    with pytest.raises(VerificationBudgetExceeded):
        client.semantic_similarity("private query", ["private comparison"])
    assert delegate.calls == ["grader"]


@pytest.mark.parametrize(
    ("method", "operation", "expected_dependency"),
    [
        ("normalizer", "normalizer", "normalizer"),
        ("grader", "grade", "grader"),
        ("similarity", "similarity", "similarity"),
        ("grader", "language", "language"),
    ],
)
def test_dependency_timeout_is_stable_and_stops_later_calls(
    method: str,
    operation: str,
    expected_dependency: str,
) -> None:
    budget = VerificationBudget(total_seconds=30, clock=FakeClock())
    delegate = TimeoutDelegate(operation)
    client = BudgetedGraderClient(delegate, budget)

    with pytest.raises(VerificationDependencyTimeout) as raised:
        if method == "normalizer":
            client.normalize_math_answer({"mathjson": 4})
        elif method == "similarity":
            client.semantic_similarity("secret query", ["secret comparison"])
        else:
            client.grade("E2", {"accepted_forms": ["secret"]}, {"text": "secret"})

    assert raised.value.dependency == expected_dependency
    assert "secret" not in str(raised.value)
    assert budget.feature_summary()["status"] == "dependency_timeout"
    assert budget.feature_summary()["terminal_dependency"] == expected_dependency

    calls_before_retry = list(delegate.calls)
    with pytest.raises(VerificationDependencyTimeout):
        client.grade("M1", {"expected": 4}, {"text": "4"})
    assert delegate.calls == calls_before_retry


def test_httpx_diagnostic_is_not_part_of_budget_exception() -> None:
    timeout = httpx.ReadTimeout(
        "https://internal.example/private payload",
        request=httpx.Request("POST", "https://internal.example/private"),
    )
    error = GraderRequestTimeoutError("grade")
    error.__cause__ = timeout

    budget = VerificationBudget(total_seconds=30, clock=FakeClock())
    delegate = TimeoutDelegate("grade")
    client = BudgetedGraderClient(delegate, budget)

    with pytest.raises(VerificationDependencyTimeout) as raised:
        client.grade("M1", {"expected": 4}, {"text": "private"})

    persisted = str(raised.value)
    assert "internal.example" not in persisted
    assert "private" not in persisted
