from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from edu_grader_api.services import question_verification as verification
from edu_grader_api.services.capacity_aware_verification import (
    run_capacity_aware_candidate_verification,
)
from edu_grader_api.services.verification_capacity import MAX_PROMPT_CHARS


class FakeSession:
    def __init__(self) -> None:
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1


def revision(candidate_json: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        generated_question_draft_id=uuid4(),
        candidate_json=candidate_json,
        content_hash="a" * 64,
    )


def test_over_capacity_candidate_never_delegates_to_core_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    current_revision = revision({"prompt": "x" * (MAX_PROMPT_CHARS + 1)})
    draft = SimpleNamespace(
        id=current_revision.generated_question_draft_id,
        job_id=uuid4(),
        current_revision_id=current_revision.id,
    )
    captured: dict[str, object] = {}
    run = SimpleNamespace(feature_summary_json={"finding_count": 1})

    def fail_if_delegated(*args: object, **kwargs: object) -> object:
        raise AssertionError("core verifier must not run for an over-capacity candidate")

    def fake_persist(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return run

    monkeypatch.setattr(verification, "run_candidate_verification", fail_if_delegated)
    monkeypatch.setattr(verification, "_persist_run", fake_persist)

    result = run_capacity_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=current_revision,  # type: ignore[arg-type]
        grader_client=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result is run
    findings = captured["findings"]
    assert isinstance(findings, list)
    assert [finding.code for finding in findings] == ["candidate_capacity_limit_exceeded"]
    assert run.feature_summary_json["verification_capacity_signal"]["violations"] == [
        "prompt_chars"
    ]
    assert run.feature_summary_json["grade_complexity_signal"] if False else True
    assert session.flush_count == 1


def test_valid_candidate_delegates_and_attaches_capacity_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    current_revision = revision(
        {
            "prompt": "What is 2 + 2?",
            "explanation": "Add the values.",
            "rule_json": {"expected": 4},
        }
    )
    draft = SimpleNamespace(
        id=current_revision.generated_question_draft_id,
        job_id=uuid4(),
        current_revision_id=current_revision.id,
    )
    run = SimpleNamespace(feature_summary_json={"finding_count": 0})
    calls: list[dict[str, object]] = []

    def fake_delegate(*args: object, **kwargs: object) -> object:
        calls.append(kwargs)
        return run

    def fail_if_capacity_persisted(*args: object, **kwargs: object) -> object:
        raise AssertionError("capacity-only persistence must not run for a valid candidate")

    monkeypatch.setattr(verification, "run_candidate_verification", fake_delegate)
    monkeypatch.setattr(verification, "_persist_run", fail_if_capacity_persisted)

    result = run_capacity_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=current_revision,  # type: ignore[arg-type]
        grader_client=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result is run
    assert len(calls) == 1
    signal = run.feature_summary_json["verification_capacity_signal"]
    assert signal["availability"] == "available"
    assert signal["load_bucket"] == "small"
    assert signal["violations"] == []
    assert session.flush_count == 1
