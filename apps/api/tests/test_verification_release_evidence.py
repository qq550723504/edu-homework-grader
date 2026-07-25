from __future__ import annotations

import json
from pathlib import Path

import pytest

from edu_grader_api.services.verification_release_evidence import (
    JSON_FILENAME,
    MARKDOWN_FILENAME,
    REPORT_VERSION,
    assert_deidentified_evidence,
    render_markdown,
    run_release_evidence,
    write_report,
)


def evidence_report() -> dict[str, object]:
    return {
        "report_version": REPORT_VERSION,
        "scenario_catalog_version": 1,
        "generated_at_utc": "2026-07-25T00:00:00+00:00",
        "source_revision": "a" * 40,
        "contracts": {
            "validator_version": "verification-v12",
            "ruleset_version": "rules-v12",
            "capacity_version": "verification-capacity-v1",
            "budget_version": "verification-budget-v1",
        },
        "protocol": {
            "repetitions": 2,
            "database": "postgresql",
            "grader": "real_http_service",
            "language_dependency": "real_languagetool_service",
            "isolation": "unique_compose_project_and_volume_per_repetition",
            "cleanup_policy": "docker_compose_down_with_volumes",
        },
        "environment": {
            "python_version": "3.13.5",
            "postgres_version": "16.9",
            "postgres_image_id": "sha256:postgres",
            "grader_image_id": "sha256:grader",
            "languagetool_image_id": "sha256:language",
        },
        "summary": {
            "repetition_count": 2,
            "scenario_count": 4,
            "all_repetitions_succeeded": True,
            "all_cleanup_succeeded": True,
        },
        "repetitions": [
            {
                "repetition": 1,
                "status": "succeeded",
                "failure_code": None,
                "scenarios": [
                    {
                        "scenario_id": "capacity_candidate_bytes",
                        "expected_status": "blocked",
                        "actual_status": "blocked",
                        "finding_codes": ["candidate_capacity_limit_exceeded"],
                        "question_version_delta": 0,
                        "external_dependency_guard": "unreachable_grader",
                        "capacity_bucket": "oversize",
                        "passed": True,
                    },
                    {
                        "scenario_id": "language_dependency_recovery",
                        "outage_status": "blocked",
                        "outage_finding_codes": ["e3_grammar_feedback_dependency"],
                        "recovery_status": "passed",
                        "recovery_finding_codes": [],
                        "old_run_immutable": True,
                        "fresh_budget_completed": True,
                        "question_version_delta": 0,
                        "passed": True,
                    },
                ],
                "cleanup": {
                    "status": "succeeded",
                    "containers_removed": True,
                    "volumes_removed": True,
                },
            },
            {
                "repetition": 2,
                "status": "succeeded",
                "failure_code": None,
                "scenarios": [],
                "cleanup": {
                    "status": "succeeded",
                    "containers_removed": True,
                    "volumes_removed": True,
                },
            },
        ],
    }


def test_release_evidence_writes_deidentified_json_and_markdown(tmp_path: Path) -> None:
    report = evidence_report()

    paths = write_report(report, tmp_path)

    assert paths.json_path == tmp_path / JSON_FILENAME
    assert paths.markdown_path == tmp_path / MARKDOWN_FILENAME
    persisted = json.loads(paths.json_path.read_text(encoding="utf-8"))
    assert persisted["summary"]["all_repetitions_succeeded"] is True
    markdown = paths.markdown_path.read_text(encoding="utf-8")
    assert "capacity_candidate_bytes" in markdown
    assert "language_dependency_recovery" in markdown
    assert "verification-v12" in markdown
    assert "http://" not in markdown


def test_release_evidence_rejects_sensitive_fields_and_locations() -> None:
    with pytest.raises(ValueError, match="forbidden field"):
        assert_deidentified_evidence({"request_payload": {"answer": "private"}})

    with pytest.raises(ValueError, match="network location"):
        assert_deidentified_evidence({"service": "https://internal.example.test"})


def test_release_evidence_markdown_rejects_invalid_repetitions() -> None:
    report = evidence_report()
    report["repetitions"] = "invalid"

    with pytest.raises(ValueError, match="repetitions"):
        render_markdown(report)


def test_release_evidence_requires_two_isolated_repetitions(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yaml"
    compose_file.write_text("services: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="at least two"):
        run_release_evidence(
            compose_file=compose_file,
            output_dir=tmp_path / "artifacts",
            repetitions=1,
        )
