from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from edu_grader_api.models import ValidationRunStatus
from edu_grader_api.services import budget_aware_verification as budgeted
from edu_grader_api.services.grader import GraderRequestTimeoutError
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.services.verification_budget import (
    VERIFICATION_BUDGET_RULESET_VERSION,
    VerificationBudgetExceeded,
    VerificationDependencyTimeout,
)


@dataclass
class FakeClock:
    current: float = 10.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    def flush(self) -> None:
        self.flush_count += 1


class PassingGrader:
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult(
            decision="auto_accepted",
            score=1,
            evidence={},
            grader_version="test-v1",
        )

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return {"type": "number", "value": "4"}

    def semantic_similarity(self, query: str, comparisons: list[str]) -> object:
        return SimpleNamespace(scores=[0.1 for _ in comparisons])


class TimeoutGrader(PassingGrader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise GraderRequestTimeoutError("grade")


def draft_and_revision() -> tuple[SimpleNamespace, SimpleNamespace]:
    draft_id = uuid4()
    return (
        SimpleNamespace(id=draft_id, job_id=uuid4()),
        SimpleNamespace(
            id=uuid4(),
            generated_question_draft_id=draft_id,
            content_hash="a" * 64,
            candidate_json={"prompt": "safe"},
        ),
    )


def validation_run(*, findings: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        validator_version="verification-v9",
        ruleset_version="rules-v9",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={"finding_count": len(findings or [])},
        findings=findings or [],
    )


def test_completed_run_gets_v10_budget_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    run = validation_run()

    monkeypatch.setattr(
        budgeted,
        "run_capacity_aware_candidate_verification",
        lambda *args, **kwargs: run,
    )
    monkeypatch.setattr(
        budgeted.settings,
        "verification_total_timeout_seconds",
        30.0,
    )

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=PassingGrader(),  # type: ignore[arg-type]
        clock=FakeClock(),
    )

    assert result is run
    assert run.validator_version == "verification-v10"
    assert run.ruleset_version == "rules-v10"
    assert run.feature_summary_json["verification_budget_signal"] == {
        "availability": "available",
        "version": VERIFICATION_BUDGET_RULESET_VERSION,
        "total_budget_seconds": 30.0,
        "status": "completed",
        "terminal_stage": None,
        "terminal_dependency": None,
    }


def test_total_timeout_is_persisted_as_stable_blocking_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    clock = FakeClock()
    persisted = validation_run()
    captured: dict[str, object] = {}

    def fake_capacity(*args: object, **kwargs: object) -> object:
        grader_client = kwargs["grader_client"]
        clock.advance(5)
        grader_client.grade("M1", {"expected": 4}, {"text": "4"})
        raise AssertionError("the deadline must block the dependency before this point")

    def fake_persist(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return persisted

    monkeypatch.setattr(
        budgeted,
        "run_capacity_aware_candidate_verification",
        fake_capacity,
    )
    monkeypatch.setattr(budgeted.core, "_persist_run", fake_persist)
    monkeypatch.setattr(
        budgeted.settings,
        "verification_total_timeout_seconds",
        5.0,
    )

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=PassingGrader(),  # type: ignore[arg-type]
        clock=clock,
    )

    assert result is persisted
    findings = captured["findings"]
    assert isinstance(findings, list)
    assert [finding.code for finding in findings] == ["verification_total_timeout"]
    assert findings[0].evidence == {
        "ruleset_version": VERIFICATION_BUDGET_RULESET_VERSION,
        "stage": "grader",
        "total_budget_seconds": 5.0,
    }
    assert "text" not in str(findings[0].evidence)
    assert persisted.status is ValidationRunStatus.PASSED
    assert persisted.validator_version == "verification-v10"


def test_swallowed_dependency_timeout_is_added_to_existing_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    generic_finding = SimpleNamespace(code="m1_grader_probe_failed")
    run = validation_run(findings=[generic_finding])
    run.status = ValidationRunStatus.BLOCKED

    def fake_capacity(*args: object, **kwargs: object) -> object:
        grader_client = kwargs["grader_client"]
        with pytest.raises(VerificationDependencyTimeout):
            grader_client.grade("M1", {"expected": 4}, {"text": "private"})
        return run

    monkeypatch.setattr(
        budgeted,
        "run_capacity_aware_candidate_verification",
        fake_capacity,
    )
    monkeypatch.setattr(
        budgeted.settings,
        "verification_total_timeout_seconds",
        30.0,
    )

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=TimeoutGrader(),  # type: ignore[arg-type]
        clock=FakeClock(),
    )

    assert result is run
    assert run.status is ValidationRunStatus.BLOCKED
    added_codes = [getattr(item, "code", None) for item in session.added]
    assert added_codes == ["grader_timeout"]
    signal = run.feature_summary_json["verification_budget_signal"]
    assert signal["status"] == "dependency_timeout"
    assert signal["terminal_dependency"] == "grader"
    assert run.feature_summary_json["finding_count"] == 2


def test_wrong_revision_is_rejected_before_budget_work() -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    revision.generated_question_draft_id = uuid4()

    with pytest.raises(ValueError, match="does not belong"):
        budgeted.run_budget_aware_candidate_verification(
            session,  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            revision=revision,  # type: ignore[arg-type]
            grader_client=PassingGrader(),  # type: ignore[arg-type]
            clock=FakeClock(),
        )

    assert session.flush_count == 0


def test_terminal_budget_prevents_later_dependency_calls() -> None:
    clock = FakeClock()
    budget = budgeted.VerificationBudget(total_seconds=1, clock=clock)
    client = budgeted.BudgetedGraderClient(PassingGrader(), budget)
    clock.advance(1)

    with pytest.raises(VerificationBudgetExceeded):
        client.grade("M1", {"expected": 4}, {"text": "4"})
    with pytest.raises(VerificationBudgetExceeded):
        client.normalize_math_answer({"mathjson": 4})
