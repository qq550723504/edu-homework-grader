from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest

from edu_grader_api.services import capacity_aware_verification as capacity_wrapper
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


def draft_for(current_revision: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        id=current_revision.generated_question_draft_id,
        job_id=uuid4(),
        current_revision_id=current_revision.id,
    )


def validation_run(*, finding_count: int) -> SimpleNamespace:
    return SimpleNamespace(
        feature_summary_json={"finding_count": finding_count},
        validator_version="verification-v8",
        ruleset_version="rules-v8",
    )


def test_over_capacity_candidate_never_delegates_to_core_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    current_revision = revision({"prompt": "x" * (MAX_PROMPT_CHARS + 1)})
    draft = draft_for(current_revision)
    captured: dict[str, object] = {}
    run = validation_run(finding_count=1)

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
    assert [finding.code for finding in findings] == [
        "candidate_capacity_limit_exceeded"
    ]
    signal = run.feature_summary_json["verification_capacity_signal"]
    assert signal["violations"] == ["prompt_chars"]
    grade_signal = captured["grade_complexity_signal"]
    assert isinstance(grade_signal, dict)
    assert grade_signal["reason"] == "capacity_preflight_blocked"
    duplicate_summary = captured["duplicate_feature_summary"]
    assert isinstance(duplicate_summary, dict)
    assert duplicate_summary["candidate_prompt_fingerprint"] is None
    assert duplicate_summary["duplicate_check_reason"] == "capacity_preflight_blocked"
    assert run.validator_version == "verification-v9"
    assert run.ruleset_version == "rules-v9"
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
    draft = draft_for(current_revision)
    run = validation_run(finding_count=0)
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
    assert run.validator_version == "verification-v9"
    assert run.ruleset_version == "rules-v9"
    assert session.flush_count == 1


def test_capacity_evaluator_failure_is_persisted_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    current_revision = revision({"prompt": "private candidate content"})
    draft = draft_for(current_revision)
    captured: dict[str, object] = {}
    run = validation_run(finding_count=1)

    def explode(candidate: object) -> object:
        raise RuntimeError("private candidate diagnostic")

    def fake_persist(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        return run

    monkeypatch.setattr(capacity_wrapper, "evaluate_verification_capacity", explode)
    monkeypatch.setattr(verification, "_persist_run", fake_persist)
    monkeypatch.setattr(
        verification,
        "run_candidate_verification",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("core verifier must not run when capacity preflight fails")
        ),
    )

    result = run_capacity_aware_candidate_verification(
        session,  # type: ignore[arg-type]
        draft=draft,  # type: ignore[arg-type]
        revision=current_revision,  # type: ignore[arg-type]
        grader_client=SimpleNamespace(),  # type: ignore[arg-type]
    )

    assert result is run
    findings = captured["findings"]
    assert isinstance(findings, list)
    assert [finding.code for finding in findings] == ["validator_unavailable"]
    assert findings[0].evidence == {"category": "capacity_preflight_unavailable"}
    signal = run.feature_summary_json["verification_capacity_signal"]
    assert signal["availability"] == "unavailable"
    assert signal["reason"] == "capacity_preflight_unavailable"
    assert "private candidate" not in str(run.feature_summary_json)
    assert run.validator_version == "verification-v9"
    assert run.ruleset_version == "rules-v9"


def test_revision_must_belong_to_draft_before_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_revision = revision({"prompt": "What is 2 + 2?"})
    draft = SimpleNamespace(
        id=uuid4(),
        job_id=uuid4(),
        current_revision_id=current_revision.id,
    )
    monkeypatch.setattr(
        capacity_wrapper,
        "evaluate_verification_capacity",
        lambda value: (_ for _ in ()).throw(
            AssertionError("capacity evaluator must not run for the wrong draft")
        ),
    )

    with pytest.raises(ValueError, match="candidate revision does not belong"):
        run_capacity_aware_candidate_verification(
            FakeSession(),  # type: ignore[arg-type]
            draft=draft,  # type: ignore[arg-type]
            revision=current_revision,  # type: ignore[arg-type]
            grader_client=SimpleNamespace(),  # type: ignore[arg-type]
        )


def test_review_service_has_no_direct_core_verification_bypass() -> None:
    from edu_grader_api.services import ai_question_review

    source = inspect.getsource(ai_question_review)
    assert "run_candidate_verification(" not in source
    assert source.count("run_capacity_aware_candidate_verification(") == 2
