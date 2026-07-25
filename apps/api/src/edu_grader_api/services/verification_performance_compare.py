"""Compare de-identified verification performance reports without enforcing thresholds."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from .verification_performance import REPORT_VERSION, assert_deidentified_report

COMPARISON_VERSION = "verification-performance-comparison-v1"
JSON_FILENAME = f"{COMPARISON_VERSION}.json"
MARKDOWN_FILENAME = f"{COMPARISON_VERSION}.md"
_METRIC_PATHS = (
    ("latency_ms", "p50"),
    ("latency_ms", "p95"),
    ("latency_ms", "p99"),
    (None, "throughput_cases_per_second"),
)
_CASE_METADATA_FIELDS = (
    "question_type",
    "load_bucket",
    "policy_version",
    "candidate_bytes",
    "expected_status",
)


def load_report(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"performance report cannot be read: {path}") from error
    if not isinstance(value, dict):
        raise ValueError("performance report must be a JSON object")
    validate_report(value)
    return value


def validate_report(report: Mapping[str, object]) -> None:
    assert_deidentified_report(report)
    if report.get("report_version") != REPORT_VERSION:
        raise ValueError("performance report version is incompatible")
    matrix_version = report.get("matrix_version")
    if isinstance(matrix_version, bool) or not isinstance(matrix_version, int) or matrix_version <= 0:
        raise ValueError("performance matrix version is invalid")
    matrix_digest = report.get("matrix_digest")
    if not isinstance(matrix_digest, str) or not matrix_digest.startswith("sha256:"):
        raise ValueError("performance matrix digest is invalid")
    source_revision = report.get("source_revision")
    if not isinstance(source_revision, str) or not source_revision.strip():
        raise ValueError("performance source revision is invalid")
    if not isinstance(report.get("contracts"), dict):
        raise ValueError("performance contracts are invalid")
    if not isinstance(report.get("protocol"), dict):
        raise ValueError("performance protocol is invalid")
    if not isinstance(report.get("environment"), dict):
        raise ValueError("performance environment is invalid")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("performance summary is invalid")
    cases = _validated_cases(report)
    case_count = summary.get("case_count")
    sample_count = summary.get("sample_count")
    failure_count = summary.get("failure_count")
    if case_count != len(cases):
        raise ValueError("performance summary case count is inconsistent")
    expected_samples = sum(_integer(case["sample_count"], "sample_count", minimum=1) for case in cases.values())
    if sample_count != expected_samples:
        raise ValueError("performance summary sample count is inconsistent")
    expected_failures = sum(
        _integer(case["failure_count"], "failure_count", minimum=0) for case in cases.values()
    )
    if failure_count != expected_failures:
        raise ValueError("performance summary failure count is inconsistent")
    all_succeeded = summary.get("all_cases_succeeded")
    if not isinstance(all_succeeded, bool) or all_succeeded != (expected_failures == 0):
        raise ValueError("performance summary success state is inconsistent")


def compare_reports(
    baseline: Mapping[str, object],
    candidate: Mapping[str, object],
    *,
    generated_at_utc: str | None = None,
) -> dict[str, object]:
    validate_report(baseline)
    validate_report(candidate)
    if baseline["matrix_version"] != candidate["matrix_version"]:
        raise ValueError("performance matrix versions are incompatible")
    if baseline["contracts"] != candidate["contracts"]:
        raise ValueError("performance verification contracts are incompatible")

    baseline_cases = _validated_cases(baseline)
    candidate_cases = _validated_cases(candidate)
    baseline_ids = set(baseline_cases)
    candidate_ids = set(candidate_cases)
    shared_ids = sorted(baseline_ids & candidate_ids)
    added_ids = sorted(candidate_ids - baseline_ids)
    removed_ids = sorted(baseline_ids - candidate_ids)

    comparisons: list[dict[str, object]] = []
    for case_id in shared_ids:
        baseline_case = baseline_cases[case_id]
        candidate_case = candidate_cases[case_id]
        if any(baseline_case[field] != candidate_case[field] for field in _CASE_METADATA_FIELDS):
            raise ValueError(f"shared performance case metadata changed: {case_id}")
        metrics: dict[str, object] = {}
        for parent, metric in _METRIC_PATHS:
            baseline_value = _metric_value(baseline_case, parent, metric)
            candidate_value = _metric_value(candidate_case, parent, metric)
            metrics[metric] = {
                "baseline": baseline_value,
                "candidate": candidate_value,
                "change_percent": percent_change(baseline_value, candidate_value),
            }
        comparisons.append(
            {
                "case_id": case_id,
                **{field: baseline_case[field] for field in _CASE_METADATA_FIELDS},
                "baseline_failure_count": baseline_case["failure_count"],
                "candidate_failure_count": candidate_case["failure_count"],
                "metrics": metrics,
            }
        )

    comparison = {
        "comparison_version": COMPARISON_VERSION,
        "report_version": REPORT_VERSION,
        "matrix_version": baseline["matrix_version"],
        "generated_at_utc": generated_at_utc or datetime.now(UTC).isoformat(),
        "policy": {
            "blocking": False,
            "thresholds": None,
            "interpretation": "observational_only",
        },
        "baseline": _report_reference(baseline),
        "candidate": _report_reference(candidate),
        "summary": {
            "comparable_case_count": len(comparisons),
            "added_case_count": len(added_ids),
            "removed_case_count": len(removed_ids),
            "matrix_changed": bool(added_ids or removed_ids),
        },
        "cases": comparisons,
        "added_cases": [_case_reference(candidate_cases[case_id]) for case_id in added_ids],
        "removed_cases": [_case_reference(baseline_cases[case_id]) for case_id in removed_ids],
    }
    assert_deidentified_report(comparison)
    return comparison


def percent_change(baseline: float, candidate: float) -> float | None:
    if not math.isfinite(baseline) or not math.isfinite(candidate):
        raise ValueError("performance metric must be finite")
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return round(((candidate - baseline) / baseline) * 100, 6)


def render_markdown(comparison: Mapping[str, object]) -> str:
    assert_deidentified_report(comparison)
    summary = comparison.get("summary")
    baseline = comparison.get("baseline")
    candidate = comparison.get("candidate")
    cases = comparison.get("cases")
    if not all(isinstance(value, Mapping) for value in (summary, baseline, candidate)):
        raise ValueError("performance comparison metadata is invalid")
    if not isinstance(cases, list):
        raise ValueError("performance comparison cases are invalid")

    lines = [
        f"# Verification performance comparison: {comparison['comparison_version']}",
        "",
        "This report is observational only. It does not apply blocking thresholds.",
        "",
        "## Reports",
        "",
        f"- Baseline revision: `{baseline['source_revision']}`",
        f"- Candidate revision: `{candidate['source_revision']}`",
        f"- Comparable cases: {summary['comparable_case_count']}",
        f"- Added cases: {summary['added_case_count']}",
        f"- Removed cases: {summary['removed_case_count']}",
        "",
        "## Comparable cases",
        "",
        "| Case | Type | Bucket | P50 % | P95 % | P99 % | Throughput % | Failures baseline → candidate |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("metrics"), Mapping):
            raise ValueError("performance comparison case is invalid")
        metrics = item["metrics"]
        lines.append(
            "| {case_id} | {question_type} | {load_bucket} | {p50} | {p95} | {p99} | "
            "{throughput} | {baseline_failures} → {candidate_failures} |".format(
                case_id=item["case_id"],
                question_type=item["question_type"],
                load_bucket=item["load_bucket"],
                p50=_display_change(metrics["p50"]),
                p95=_display_change(metrics["p95"]),
                p99=_display_change(metrics["p99"]),
                throughput=_display_change(metrics["throughput_cases_per_second"]),
                baseline_failures=item["baseline_failure_count"],
                candidate_failures=item["candidate_failure_count"],
            )
        )
    lines.extend(_change_section("Added cases", comparison.get("added_cases")))
    lines.extend(_change_section("Removed cases", comparison.get("removed_cases")))
    lines.append("")
    return "\n".join(lines)


def write_comparison(comparison: Mapping[str, object], output_dir: Path) -> tuple[Path, Path]:
    assert_deidentified_report(comparison)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    markdown_path = output_dir / MARKDOWN_FILENAME
    json_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(comparison), encoding="utf-8")
    return json_path, markdown_path


def _validated_cases(report: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    values = report.get("cases")
    if not isinstance(values, list) or not values:
        raise ValueError("performance cases are invalid")
    cases: dict[str, Mapping[str, object]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise ValueError("performance case must be an object")
        case_id = value.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in cases:
            raise ValueError("performance case identifier is invalid")
        if value.get("question_type") not in {"M1", "M2", "E1", "E2", "E3", "E4"}:
            raise ValueError("performance question type is invalid")
        if value.get("load_bucket") not in {"small", "medium", "large"}:
            raise ValueError("performance load bucket is invalid")
        if not isinstance(value.get("policy_version"), str):
            raise ValueError("performance policy version is invalid")
        _integer(value.get("candidate_bytes"), "candidate_bytes", minimum=1)
        if not isinstance(value.get("expected_status"), str):
            raise ValueError("performance expected status is invalid")
        sample_count = _integer(value.get("sample_count"), "sample_count", minimum=1)
        failure_count = _integer(value.get("failure_count"), "failure_count", minimum=0)
        if failure_count > sample_count:
            raise ValueError("performance failure count exceeds sample count")
        status_counts = value.get("status_counts")
        if not isinstance(status_counts, dict) or not status_counts:
            raise ValueError("performance status counts are invalid")
        status_total = 0
        for status, count in status_counts.items():
            if not isinstance(status, str) or not status:
                raise ValueError("performance status name is invalid")
            status_total += _integer(count, "status count", minimum=0)
        if status_total != sample_count:
            raise ValueError("performance status counts are inconsistent")
        latency = value.get("latency_ms")
        if not isinstance(latency, dict):
            raise ValueError("performance latency metrics are invalid")
        latency_values = [
            _finite_number(latency.get(metric), f"latency {metric}", minimum=0)
            for metric in ("minimum", "p50", "p95", "p99", "maximum")
        ]
        if latency_values != sorted(latency_values):
            raise ValueError("performance latency metrics are not monotonic")
        _finite_number(
            value.get("throughput_cases_per_second"),
            "throughput",
            minimum=0,
        )
        cases[case_id] = value
    return cases


def _integer(value: object, name: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"performance {name} is invalid")
    return value


def _finite_number(value: object, name: str, *, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"performance {name} is invalid")
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < minimum:
        raise ValueError(f"performance {name} is invalid")
    return numeric


def _metric_value(case: Mapping[str, object], parent: str | None, metric: str) -> float:
    container: Mapping[str, object] = case
    if parent is not None:
        value = case.get(parent)
        if not isinstance(value, dict):
            raise ValueError(f"performance metric container is invalid: {parent}")
        container = value
    return _finite_number(container.get(metric), metric, minimum=0)


def _report_reference(report: Mapping[str, object]) -> dict[str, object]:
    return {
        "source_revision": report["source_revision"],
        "matrix_digest": report["matrix_digest"],
        "generated_at_utc": report.get("generated_at_utc"),
        "summary": report["summary"],
        "environment": report["environment"],
    }


def _case_reference(case: Mapping[str, object]) -> dict[str, object]:
    return {
        "case_id": case["case_id"],
        **{field: case[field] for field in _CASE_METADATA_FIELDS},
    }


def _display_change(metric: object) -> str:
    if not isinstance(metric, Mapping):
        raise ValueError("comparison metric is invalid")
    value = metric.get("change_percent")
    return "n/a" if value is None else f"{value:+.3f}%"


def _change_section(title: str, value: object) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("comparison case change list is invalid")
    lines = ["", f"## {title}", ""]
    if not value:
        lines.append("None.")
        return lines
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("comparison changed case is invalid")
        lines.append(
            f"- `{item['case_id']}` ({item['question_type']}, {item['load_bucket']})"
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/verification-performance-comparison"),
    )
    arguments = parser.parse_args(argv)
    comparison = compare_reports(
        load_report(arguments.baseline),
        load_report(arguments.candidate),
    )
    json_path, markdown_path = write_comparison(comparison, arguments.output_dir)
    print(json_path)
    print(markdown_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
