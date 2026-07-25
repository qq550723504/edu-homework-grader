from __future__ import annotations

import pytest

from edu_grader_api.services import grader as adapter
from edu_grader_api.services.grader import HttpGraderClient
from edu_grader_api.services.verification_budget import (
    BudgetedGraderClient,
    VerificationBudget,
    VerificationDependencyTimeout,
)


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "decision": "needs_review",
            "score": 0,
            "grader_version": "test-v1",
            "signals": [{"kind": "dependency_timeout", "dependency": "language"}],
        }


def test_language_timeout_signal_terminates_shared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        adapter.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )
    budget = VerificationBudget(total_seconds=30, clock=lambda: 10.0)
    client = BudgetedGraderClient(
        HttpGraderClient("http://localhost:8010"),
        budget,
    )

    with pytest.raises(VerificationDependencyTimeout) as raised:
        client.grade(
            "E3",
            {"grammar_feedback_required": True, "max_score": 1},
            {"format": "text-v1", "text": "safe candidate"},
            policy_version="1",
        )

    assert raised.value.dependency == "language"
    assert budget.feature_summary() == {
        "availability": "available",
        "version": "verification-budget-v1",
        "total_budget_seconds": 30.0,
        "status": "dependency_timeout",
        "terminal_stage": None,
        "terminal_dependency": "language",
    }
