from pathlib import Path

import pytest

from edu_grader_api.services import operational_evaluation_executor as executor


SPEC_JSON = '{"spec_id":"operational-v1","export":{"tenant_id":"tenant-1"}}'
SIGNED_REPORT = {"report": {"promotion_eligible": False}, "signature": "signed"}


def test_executor_posts_signed_report_without_exported_records(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(executor, "build_signed_report", lambda _spec: SIGNED_REPORT)
    monkeypatch.setattr(
        executor, "post_completion", lambda **kwargs: posted.append(kwargs["payload"])
    )

    result = executor.run_executor(
        spec_json=SPEC_JSON,
        callback_url="http://api:8000/callback",
        callback_token="token",
        output_dir=tmp_path,
    )

    assert result == 0
    assert posted == [{"report": SIGNED_REPORT}]
    assert "records" not in str(posted)


def test_executor_maps_failure_to_a_sanitized_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    posted: list[dict[str, object]] = []
    monkeypatch.setattr(
        executor,
        "build_signed_report",
        lambda _spec: (_ for _ in ()).throw(ValueError("raw prompt")),
    )
    monkeypatch.setattr(
        executor, "post_completion", lambda **kwargs: posted.append(kwargs["payload"])
    )

    result = executor.run_executor(
        spec_json=SPEC_JSON,
        callback_url="http://api:8000/callback",
        callback_token="token",
        output_dir=tmp_path,
    )

    assert result == 1
    assert posted == [{"failure_code": "evaluation_execution_failed"}]
