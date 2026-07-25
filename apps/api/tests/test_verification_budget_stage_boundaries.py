from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from uuid import uuid4

import pytest

from edu_grader_api.services import capacity_aware_verification as capacity
from edu_grader_api.services import question_verification as core
from edu_grader_api.services.verification_budget import (
    VerificationBudget,
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


def draft_and_revision() -> tuple[SimpleNamespace, SimpleNamespace]:
    draft_id = uuid4()
    revision_id = uuid4()
    return (
        SimpleNamespace(
            id=draft_id,
            job_id=uuid4(),
            current_revision_id=revision_id,
        ),
        SimpleNamespace(
            id=revision_id,
            generated_question_draft_id=draft_id,
            candidate_json={"prompt": "safe candidate"},
            content_hash="a" * 64,
        ),
    )


def test_capacity_preflight_post_boundary_propagates_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=1, clock=clock)
    draft, revision = draft_and_revision()

    def evaluate(candidate: object) -> object:
        clock.advance(1)
        return SimpleNamespace(blocked=False, feature_summary=lambda: {})

    monkeypatch.setattr(capacity, "evaluate_verification_capacity", evaluate)
    monkeypatch.setattr(
        capacity.verification,
        "run_candidate_verification",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("core verification must not start after timeout")
        ),
    )

    with pytest.raises(VerificationBudgetExceeded) as raised:
        capacity.run_capacity_aware_candidate_verification(
            SimpleNamespace(),  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            revision=revision,  # type: ignore[arg-type]
            grader_client=SimpleNamespace(),  # type: ignore[arg-type]
            budget=budget,
        )

    assert raised.value.stage == "capacity_preflight"


def test_duplicate_query_post_boundary_propagates_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=1, clock=clock)
    draft, revision = draft_and_revision()

    class FakeSession:
        def get(self, model: object, key: object) -> object:
            return SimpleNamespace(tenant_id=uuid4())

    original_capture = core._capture_duplicate_snapshot

    def capture(*args: object, **kwargs: object) -> object:
        clock.advance(1)
        return original_capture(*args, **kwargs)

    monkeypatch.setattr(core, "_capture_duplicate_snapshot", capture)
    monkeypatch.setattr(
        core,
        "_evaluate_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("candidate evaluation must not start after timeout")
        ),
    )

    class SnapshotSession(FakeSession):
        def execute(self, statement: object) -> object:
            return SimpleNamespace(first=lambda: None, all=lambda: [])

        def scalars(self, statement: object) -> list[object]:
            return []

    with pytest.raises(VerificationBudgetExceeded) as raised:
        core.run_candidate_verification(
            SnapshotSession(),  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            revision=revision,  # type: ignore[arg-type]
            grader_client=SimpleNamespace(),  # type: ignore[arg-type]
            budget=budget,
        )

    assert raised.value.stage == "duplicate_check"


def test_persist_boundary_runs_before_database_writes() -> None:
    clock = FakeClock()
    budget = VerificationBudget(total_seconds=1, clock=clock)
    clock.advance(1)
    draft, revision = draft_and_revision()

    class NoWriteSession:
        def flush(self) -> None:
            raise AssertionError("persistence must not start after timeout")

    with pytest.raises(VerificationBudgetExceeded) as raised:
        core._persist_run(
            NoWriteSession(),  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            evaluated_revision_id=revision.id,
            evaluated_revision_hash=revision.content_hash,
            findings=[],
            duplicate_feature_summary={},
            difficulty_signal={},
            grade_complexity_signal={},
            objective_prerequisite_signal={},
            math_semantics_signal={},
            budget=budget,
        )

    assert raised.value.stage == "persist"


def test_terminal_dependency_timeout_prevents_generic_run_persistence() -> None:
    budget = VerificationBudget(total_seconds=30, clock=FakeClock())
    budget.mark_dependency_timeout("grader")
    draft, revision = draft_and_revision()

    class NoWriteSession:
        def flush(self) -> None:
            raise AssertionError("generic persistence must not start after dependency timeout")

    with pytest.raises(VerificationDependencyTimeout) as raised:
        core._persist_run(
            NoWriteSession(),  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            evaluated_revision_id=revision.id,
            evaluated_revision_hash=revision.content_hash,
            findings=[],
            duplicate_feature_summary={},
            difficulty_signal={},
            grade_complexity_signal={},
            objective_prerequisite_signal={},
            math_semantics_signal={},
            budget=budget,
        )

    assert raised.value.dependency == "grader"
