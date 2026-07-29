from __future__ import annotations

import json
from pathlib import Path

import pytest

from edu_grader_api.services import verification_release_evidence as evidence
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


def test_compose_context_overrides_environment_for_every_compose_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(
        command: list[str],
        *,
        check: bool,
        env: dict[str, str],
    ) -> None:
        captured["command"] = command
        captured["check"] = check
        captured["environment"] = env

    monkeypatch.setattr(evidence.subprocess, "run", fake_run)
    context = evidence.ComposeContext(
        compose_file=Path("compose.yaml"),
        project_name="evidence-test",
        database_url="postgresql://example",
        grader_url="http://grader",
        languagetool_health_url="http://languagetool",
        compose_environment={"RELEASE_EVIDENCE_LANGUAGE_CONNECT_TIMEOUT_HOST": "172.29.254.247"},
    )

    evidence._compose(context, "config", "--quiet")

    assert captured["check"] is True
    assert captured["environment"] == {
        **__import__("os").environ,
        "RELEASE_EVIDENCE_LANGUAGE_CONNECT_TIMEOUT_HOST": "172.29.254.247",
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


def test_release_evidence_compose_accepts_candidate_image_overrides() -> None:
    compose = Path("infra/release-evidence/compose.yaml").read_text(encoding="utf-8")

    assert "${RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE:-" in compose
    assert compose.count("${RELEASE_EVIDENCE_GRADER_IMAGE:-") == 2


def test_reusable_evidence_workflow_pulls_published_candidate_images() -> None:
    workflow = Path(".github/workflows/verification-release-evidence.yml").read_text(
        encoding="utf-8"
    )

    assert "packages: read" in workflow
    assert "docker/login-action@" in workflow
    assert 'docker pull "$RELEASE_EVIDENCE_GRADER_IMAGE"' in workflow
    assert 'docker pull "$RELEASE_EVIDENCE_LANGUAGETOOL_IMAGE"' in workflow


def test_source_revision_prefers_explicit_evidence_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RELEASE_EVIDENCE_SOURCE_REVISION", "head-sha")
    monkeypatch.setenv("GITHUB_SHA", "merge-sha")

    assert evidence._source_revision() == "head-sha"


class _RecoveringLanguageGrader:
    def __init__(self) -> None:
        self.calls = 0

    def grade(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        if self.calls == 1:
            raise evidence.GraderRequestTimeoutError("language")
        return object()


def test_language_dependency_readiness_retries_without_persisting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grader = _RecoveringLanguageGrader()
    monkeypatch.setattr(evidence.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(evidence.time, "sleep", lambda seconds: None)

    evidence._wait_for_language_dependency(  # type: ignore[arg-type]
        grader,
        timeout_seconds=1,
    )

    assert grader.calls == 2


class _WarmupResponse:
    status = 200

    def __enter__(self) -> "_WarmupResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_language_tool_warmup_uses_check_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, *, timeout: float) -> _WarmupResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return _WarmupResponse()

    monkeypatch.setattr(evidence, "urlopen", fake_urlopen)
    evidence._warm_language_tool(
        "http://127.0.0.1:58011/v2/languages",
        timeout_seconds=120,
    )

    request = captured["request"]
    assert getattr(request, "full_url").endswith("/v2/check")
    assert captured["timeout"] == 120


class _CapturingLanguageGrader:
    def __init__(self) -> None:
        self.answer_json: dict[str, object] | None = None

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> object:
        self.answer_json = answer_json
        return object()


def test_language_dependency_readiness_uses_text_v1_envelope() -> None:
    grader = _CapturingLanguageGrader()

    evidence._wait_for_language_dependency(  # type: ignore[arg-type]
        grader,
        timeout_seconds=1,
    )

    assert grader.answer_json == {
        "format": "text-v1",
        "text": "I travelled by train.",
    }


class _InvalidContractGrader:
    def __init__(self) -> None:
        self.calls = 0

    def grade(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        raise ValueError("invalid local adapter contract")


def test_language_dependency_readiness_does_not_mask_contract_errors() -> None:
    grader = _InvalidContractGrader()

    with pytest.raises(ValueError, match="invalid local adapter contract"):
        evidence._wait_for_language_dependency(  # type: ignore[arg-type]
            grader,
            timeout_seconds=1,
        )

    assert grader.calls == 1
