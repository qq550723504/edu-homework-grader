from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from edu_grader_api.services.verification_performance import REPORT_VERSION
from edu_grader_api.services.verification_performance_compare import (
    COMPARISON_VERSION,
    JSON_FILENAME,
    MARKDOWN_FILENAME,
    compare_reports,
    load_report,
    percent_change,
    render_markdown,
    validate_report,
    write_comparison,
)


def report(*, revision: str, case_ids: tuple[str, ...] = ("M1-small",)) -> dict[str, object]:
    cases = []
    for index, case_id in enumerate(case_ids, start=1):
        question_type, load_bucket = case_id.split("-", maxsplit=1)
        cases.append(
            {
                "case_id": case_id,
                "question_type": question_type,
                "load_bucket": load_bucket,
                "policy_version": "1",
                "candidate_bytes": 1000 * index,
                "expected_status": "passed",
                "sample_count": 5,
                "failure_count": 0,
                "status_counts": {"passed": 5},
                "latency_ms": {
                    "minimum": 1.0 * index,
                    "p50": 2.0 * index,
                    "p95": 3.0 * index,
                    "p99": 4.0 * index,
                    "maximum": 5.0 * index,
                },
                "throughput_cases_per_second": 100.0 / index,
            }
        )
    return {
        "report_version": REPORT_VERSION,
        "matrix_version": 1,
        "matrix_digest": f"sha256:{revision:0<64}"[:71],
        "generated_at_utc": "2026-07-25T00:00:00+00:00",
        "source_revision": revision,
        "contracts": {
            "validator_version": "verification-v12",
            "ruleset_version": "rules-v12",
            "capacity_version": "verification-capacity-v1",
            "budget_version": "verification-budget-v1",
        },
        "protocol": {
            "warmup_runs": 1,
            "measured_runs": 5,
            "concurrency": 1,
            "seed": 119,
            "clock": "perf_counter_ns",
            "percentile_method": "R-7 linear interpolation",
            "outlier_policy": "none",
            "failure_policy": "retain every measured sample",
        },
        "environment": {"runner": "test", "cpu_count": 1},
        "summary": {
            "case_count": len(cases),
            "sample_count": len(cases) * 5,
            "failure_count": 0,
            "all_cases_succeeded": True,
        },
        "cases": cases,
    }


def test_compare_reports_calculates_observational_metric_changes() -> None:
    baseline = report(revision="baseline")
    candidate = report(revision="candidate")
    candidate_case = candidate["cases"][0]
    candidate_case["latency_ms"]["p50"] = 2.5
    candidate_case["latency_ms"]["p95"] = 2.7
    candidate_case["latency_ms"]["p99"] = 4.4
    candidate_case["throughput_cases_per_second"] = 80.0

    comparison = compare_reports(
        baseline,
        candidate,
        generated_at_utc="2026-07-25T01:00:00+00:00",
    )

    assert comparison["comparison_version"] == COMPARISON_VERSION
    assert comparison["policy"] == {
        "blocking": False,
        "thresholds": None,
        "interpretation": "observational_only",
    }
    assert comparison["summary"] == {
        "comparable_case_count": 1,
        "added_case_count": 0,
        "removed_case_count": 0,
        "matrix_changed": False,
    }
    metrics = comparison["cases"][0]["metrics"]
    assert metrics["p50"]["change_percent"] == 25.0
    assert metrics["p95"]["change_percent"] == -10.0
    assert metrics["p99"]["change_percent"] == 10.0
    assert metrics["throughput_cases_per_second"]["change_percent"] == -20.0


def test_compare_reports_lists_added_and_removed_cases() -> None:
    baseline = report(revision="baseline", case_ids=("M1-small", "M2-small"))
    candidate = report(revision="candidate", case_ids=("M1-small", "E1-small"))

    comparison = compare_reports(baseline, candidate)

    assert comparison["summary"] == {
        "comparable_case_count": 1,
        "added_case_count": 1,
        "removed_case_count": 1,
        "matrix_changed": True,
    }
    assert [item["case_id"] for item in comparison["added_cases"]] == ["E1-small"]
    assert [item["case_id"] for item in comparison["removed_cases"]] == ["M2-small"]


def test_shared_case_metadata_changes_fail_closed() -> None:
    baseline = report(revision="baseline")
    candidate = report(revision="candidate")
    candidate["cases"][0]["candidate_bytes"] = 2000

    with pytest.raises(ValueError, match="metadata changed"):
        compare_reports(baseline, candidate)


def test_incompatible_contracts_fail_closed() -> None:
    baseline = report(revision="baseline")
    candidate = report(revision="candidate")
    candidate["contracts"]["ruleset_version"] = "rules-v13"

    with pytest.raises(ValueError, match="contracts"):
        compare_reports(baseline, candidate)


def test_validate_report_rejects_corrupt_summary_and_latency() -> None:
    corrupt_summary = report(revision="baseline")
    corrupt_summary["summary"]["sample_count"] = 4
    with pytest.raises(ValueError, match="sample count"):
        validate_report(corrupt_summary)

    corrupt_latency = report(revision="baseline")
    corrupt_latency["cases"][0]["latency_ms"]["p95"] = 1.0
    with pytest.raises(ValueError, match="not monotonic"):
        validate_report(corrupt_latency)


def test_load_report_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be read"):
        load_report(path)


def test_percent_change_handles_zero_baseline() -> None:
    assert percent_change(0, 0) == 0
    assert percent_change(0, 1) is None
    assert percent_change(100, 125) == 25


def test_comparison_outputs_json_and_markdown(tmp_path: Path) -> None:
    comparison = compare_reports(
        report(revision="baseline"),
        report(revision="candidate"),
        generated_at_utc="2026-07-25T01:00:00+00:00",
    )

    json_path, markdown_path = write_comparison(comparison, tmp_path)

    assert json_path == tmp_path / JSON_FILENAME
    assert markdown_path == tmp_path / MARKDOWN_FILENAME
    assert json.loads(json_path.read_text(encoding="utf-8")) == comparison
    markdown = markdown_path.read_text(encoding="utf-8")
    assert markdown == render_markdown(comparison)
    assert "observational only" in markdown
    assert "M1-small" in markdown


def test_comparison_never_contains_report_case_content() -> None:
    baseline = report(revision="baseline")
    candidate = deepcopy(baseline)
    candidate["source_revision"] = "candidate"

    comparison = compare_reports(baseline, candidate)
    encoded = json.dumps(comparison, sort_keys=True)

    assert "prompt" not in encoded
    assert "rule_json" not in encoded
    assert "http://" not in encoded
    assert "https://" not in encoded
