from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from edu_grader_api.models import ValidationFindingSeverity, ValidationRunStatus
from edu_grader_api.services import budget_aware_verification as budgeted
from edu_grader_api.services.grader import GraderRequestTimeoutError
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.services.verification_budget import (
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
        self.flush_count = 0

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
        return GradeResult("auto_accepted", 1, {}, "test-v1")

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


def validation_run() -> SimpleNamespace:
    return SimpleNamespace(
        validator_version="verification-v9",
        ruleset_version="rules-v9",
        status=ValidationRunStatus.PASSED,
        feature_summary_json={"finding_count": 0},
        findings=[],
    )


def apply_plan(
    run: SimpleNamespace,
    finalizer: budgeted.core.VerificationPersistenceFinalizer,
    *,
    findings: tuple[object, ...] = (),
) -> budgeted.core.VerificationPersistencePlan:
    plan = finalizer(
        budgeted.core.VerificationPersistencePlan(
            findings=findings,  # type: ignore[arg-type]
            validator_version="verification-v9",
            ruleset_version="rules-v9",
            feature_summary_extensions={},
        )
    )
    run.validator_version = plan.validator_version
    run.ruleset_version = plan.ruleset_version
    run.findings = list(plan.findings)
    run.feature_summary_json = {
        "finding_count": len(plan.findings),
        **plan.feature_summary_extensions,
    }
    if any(
        getattr(finding, "severity", None) is ValidationFindingSeverity.BLOCKED
        for finding in plan.findings
    ):
        run.status = ValidationRunStatus.BLOCKED
    return plan


def test_completed_run_gets_v12_budget_signal_before_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    run = validation_run()

    def fake_capacity(*args: object, **kwargs: object) -> object:
        finalizer = kwargs["persistence_finalizer"]
        assert callable(finalizer)
        apply_plan(run, finalizer)
        return run

    monkeypatch.setattr(budgeted, "run_capacity_aware_candidate_verification", fake_capacity)
    monkeypatch.setattr(budgeted.settings, "verification_total_timeout_seconds", 30.0)

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=PassingGrader(),  # type: ignore[arg-type]
        clock=FakeClock(),
    )

    assert result is run
    assert run.validator_version == "verification-v12"
    assert run.ruleset_version == "rules-v12"
    assert run.feature_summary_json["verification_budget_signal"]["status"] == "completed"
    assert session.flush_count == 0


def test_total_timeout_is_persisted_in_one_final_plan(
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
        raise AssertionError("deadline must block the dependency")

    def fake_persist(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        finalizer = kwargs["persistence_finalizer"]
        assert callable(finalizer)
        apply_plan(
            persisted,
            finalizer,
            findings=tuple(kwargs["findings"]),
        )
        return persisted

    monkeypatch.setattr(budgeted, "run_capacity_aware_candidate_verification", fake_capacity)
    monkeypatch.setattr(budgeted.core, "_persist_run", fake_persist)
    monkeypatch.setattr(budgeted.settings, "verification_total_timeout_seconds", 5.0)

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=PassingGrader(),  # type: ignore[arg-type]
        clock=clock,
    )

    assert result is persisted
    assert [finding.code for finding in persisted.findings] == ["verification_total_timeout"]
    assert persisted.status is ValidationRunStatus.BLOCKED
    assert persisted.validator_version == "verification-v12"
    signal = persisted.feature_summary_json["verification_budget_signal"]
    assert signal["status"] == "total_timeout"
    assert signal["terminal_stage"] == "grader"


def test_swallowed_dependency_timeout_is_in_final_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    draft, revision = draft_and_revision()
    run = validation_run()
    generic = budgeted.core.VerificationFinding(
        code="m1_grader_probe_failed",
        severity=ValidationFindingSeverity.BLOCKED,
        evidence={"probe": "grader"},
        remediation="Retry validation.",
    )

    def fake_capacity(*args: object, **kwargs: object) -> object:
        grader_client = kwargs["grader_client"]
        with pytest.raises(VerificationDependencyTimeout):
            grader_client.grade("M1", {"expected": 4}, {"text": "private"})
        finalizer = kwargs["persistence_finalizer"]
        assert callable(finalizer)
        apply_plan(run, finalizer, findings=(generic,))
        return run

    monkeypatch.setattr(budgeted, "run_capacity_aware_candidate_verification", fake_capacity)
    monkeypatch.setattr(budgeted.settings, "verification_total_timeout_seconds", 30.0)

    result = budgeted.run_budget_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=revision,  # type: ignore[arg-type]
        grader_client=TimeoutGrader(),  # type: ignore[arg-type]
        clock=FakeClock(),
    )

    assert result is run
    assert [finding.code for finding in run.findings] == [
        "m1_grader_probe_failed",
        "grader_timeout",
    ]
    signal = run.feature_summary_json["verification_budget_signal"]
    assert signal["status"] == "dependency_timeout"
    assert signal["terminal_dependency"] == "grader"


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
