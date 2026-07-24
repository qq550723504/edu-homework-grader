from __future__ import annotations

from edu_grader_api.routers.ai_question_validation import (
    _public_feature_summary,
    _public_finding_evidence,
)


def test_public_budget_signal_exposes_only_contract_status() -> None:
    summary = {
        "finding_count": 1,
        "verification_budget_signal": {
            "availability": "available",
            "version": "verification-budget-v1",
            "total_budget_seconds": 30.0,
            "status": "total_timeout",
            "terminal_stage": "private-internal-stage",
            "terminal_dependency": "private-dependency",
            "elapsed_seconds": 30.001,
            "started_at": 123.0,
            "private_payload": "student content",
        },
    }

    public = _public_feature_summary(summary)

    assert public["verification_budget_signal"] == {
        "availability": "available",
        "version": "verification-budget-v1",
        "total_budget_seconds": 30.0,
        "status": "total_timeout",
    }
    assert "student content" not in str(public)
    assert "elapsed" not in str(public)
    assert "started" not in str(public)


def test_public_timeout_finding_exposes_stable_classification_only() -> None:
    public = _public_finding_evidence(
        {
            "ruleset_version": "verification-budget-v1",
            "stage": "grader",
            "dependency": "grader",
            "total_budget_seconds": 30.0,
            "url": "https://internal.example/private",
            "payload": "student answer",
            "exception": "read timeout containing internal diagnostics",
        }
    )

    assert public == {
        "ruleset_version": "verification-budget-v1",
        "stage": "grader",
        "dependency": "grader",
        "total_budget_seconds": 30.0,
    }
