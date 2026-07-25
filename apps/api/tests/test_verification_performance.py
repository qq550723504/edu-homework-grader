from __future__ import annotations

import json
from pathlib import Path

import pytest

from edu_grader_api.services.verification_performance import (
    JSON_FILENAME,
    MARKDOWN_FILENAME,
    REPORT_VERSION,
    SyntheticVerificationExecutor,
    assert_deidentified_report,
    build_benchmark_cases,
    percentile_r7,
    render_markdown,
    run_benchmark,
    write_report,
)


def test_matrix_contains_every_question_type_and_load_bucket() -> None:
    cases = build_benchmark_cases()

    assert len(cases) == 18
    assert {case.case_id for case in cases} == {
        f"{question_type}-{bucket}"
        for question_type in ("M1", "M2", "E1", "E2", "E3", "E4")
        for bucket in ("small", "medium", "large")
    }
    assert all(case.expected_status == "passed" for case in cases)
    assert all(case.candidate_bytes > 0 for case in cases)


@pytest.mark.parametrize(
    ("percentile", "expected"),
    [(0, 1.0), (50, 2.5), (95, 3.85), (99, 3.97), (100, 4.0)],
)
def test_percentile_r7_uses_linear_interpolation(
    percentile: float,
    expected: float,
) -> None:
    assert percentile_r7([1, 2, 3, 4], percentile) == pytest.approx(expected)


def test_percentile_rejects_empty_or_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="at least one"):
        percentile_r7([], 50)
    with pytest.raises(ValueError, match="between 0 and 100"):
        percentile_r7([1], 101)


def test_benchmark_protocol_retains_every_sample_and_failure() -> None:
    case = build_benchmark_cases()[0]
    outcomes = iter(["passed", "blocked", "passed"])
    clock_values = iter([0, 1_000_000, 2_000_000, 4_000_000, 5_000_000, 8_000_000])

    report = run_benchmark(
        [case],
        lambda _case: next(outcomes),
        warmup_runs=0,
        measured_runs=3,
        seed=7,
        clock_ns=lambda: next(clock_values),
        environment={"runner": "test", "cpu_count": 1},
        generated_at_utc="2026-07-25T00:00:00+00:00",
        source_revision="test-sha",
    )

    assert report["report_version"] == REPORT_VERSION
    assert report["summary"] == {
        "case_count": 1,
        "sample_count": 3,
        "failure_count": 1,
        "all_cases_succeeded": False,
    }
    result = report["cases"][0]
    assert result["status_counts"] == {"blocked": 1, "passed": 2}
    assert result["failure_count"] == 1
    assert result["latency_ms"] == {
        "minimum": 1.0,
        "p50": 2.0,
        "p95": 2.9,
        "p99": 2.98,
        "maximum": 3.0,
    }
    assert result["throughput_cases_per_second"] == 500.0


def test_report_contains_only_deidentified_case_metadata() -> None:
    case = build_benchmark_cases()[0]
    report = run_benchmark(
        [case],
        lambda _case: "passed",
        warmup_runs=0,
        measured_runs=1,
        clock_ns=iter([0, 1_000_000]).__next__,
        environment={"runner": "test"},
        generated_at_utc="2026-07-25T00:00:00+00:00",
        source_revision="test-sha",
    )
    encoded = json.dumps(report, sort_keys=True)

    assert case.candidate["prompt"] not in encoded
    assert "benchmark_payload_padding" not in encoded
    assert "rule_json" not in encoded
    assert "objective_revision_id" not in encoded
    assert "http://" not in encoded
    assert "https://" not in encoded


@pytest.mark.parametrize(
    "value",
    [
        {"prompt": "private"},
        {"nested": {"rule_json": {}}},
        {"value": "https://internal.example.test"},
    ],
)
def test_report_privacy_guard_fails_closed(value: object) -> None:
    with pytest.raises(ValueError):
        assert_deidentified_report(value)


def test_json_and_markdown_reports_are_written(tmp_path: Path) -> None:
    case = build_benchmark_cases()[0]
    report = run_benchmark(
        [case],
        lambda _case: "passed",
        warmup_runs=0,
        measured_runs=1,
        clock_ns=iter([0, 1_000_000]).__next__,
        environment={"runner": "test", "cpu_count": 1},
        generated_at_utc="2026-07-25T00:00:00+00:00",
        source_revision="test-sha",
    )

    paths = write_report(report, tmp_path)

    assert paths.json_path == tmp_path / JSON_FILENAME
    assert paths.markdown_path == tmp_path / MARKDOWN_FILENAME
    assert json.loads(paths.json_path.read_text(encoding="utf-8")) == report
    markdown = paths.markdown_path.read_text(encoding="utf-8")
    assert markdown == render_markdown(report)
    assert "| Case | Type | Bucket |" in markdown
    assert case.case_id in markdown


def test_synthetic_executor_runs_all_18_cases_through_production_wrapper() -> None:
    cases = build_benchmark_cases()

    with SyntheticVerificationExecutor(cases) as executor:
        statuses = {case.case_id: executor(case) for case in cases}

    assert statuses == {case.case_id: "passed" for case in cases}
