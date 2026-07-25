"""De-identified release evidence for verification capacity and dependency recovery."""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Mapping
from urllib.request import urlopen

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationValidationRun,
    QuestionVersion,
)
from .budget_aware_verification import (
    BUDGET_AWARE_RULESET_VERSION,
    BUDGET_AWARE_VALIDATOR_VERSION,
    run_budget_aware_candidate_verification,
)
from .grader import HttpGraderClient
from .verification_budget import VERIFICATION_BUDGET_RULESET_VERSION
from .verification_capacity import (
    MAX_CANDIDATE_BYTES,
    VERIFICATION_CAPACITY_RULESET_VERSION,
    evaluate_verification_capacity,
)
from .verification_performance import (
    BenchmarkCase,
    _base_candidate,
    _create_synthetic_draft,
)

REPORT_VERSION = "verification-release-evidence-v1"
SCENARIO_CATALOG_VERSION = 1
JSON_FILENAME = f"{REPORT_VERSION}.json"
MARKDOWN_FILENAME = f"{REPORT_VERSION}.md"
DEFAULT_REPETITIONS = 2
DEFAULT_DATABASE_URL = (
    "postgresql+psycopg://release_evidence:release-evidence-password"
    "@127.0.0.1:55432/release_evidence"
)
DEFAULT_GRADER_URL = "http://127.0.0.1:58010"
DEFAULT_LANGUAGETOOL_HEALTH_URL = "http://127.0.0.1:58011/v2/languages"

_FORBIDDEN_KEY_FRAGMENTS = (
    "prompt",
    "reading_material",
    "expected_answer",
    "rule_json",
    "assertion",
    "payload",
    "exception",
    "traceback",
    "url",
    "token",
    "cookie",
    "authorization",
    "database_dsn",
    "database_url",
)


class ProductRegression(RuntimeError):
    """Stable product-regression code without candidate or dependency diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ComposeContext:
    compose_file: Path
    project_name: str
    database_url: str
    grader_url: str
    languagetool_health_url: str

    @property
    def command_prefix(self) -> list[str]:
        return [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--file",
            str(self.compose_file),
        ]


@dataclass(frozen=True, slots=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


def run_release_evidence(
    *,
    compose_file: Path,
    output_dir: Path,
    repetitions: int = DEFAULT_REPETITIONS,
    database_url: str = DEFAULT_DATABASE_URL,
    grader_url: str = DEFAULT_GRADER_URL,
    languagetool_health_url: str = DEFAULT_LANGUAGETOOL_HEALTH_URL,
) -> tuple[dict[str, object], ReportPaths]:
    if repetitions < 2:
        raise ValueError("release evidence requires at least two repetitions")
    if not compose_file.is_file():
        raise ValueError("release evidence compose file does not exist")

    repetition_reports: list[dict[str, object]] = []
    environment: dict[str, object] = runtime_environment()
    for repetition in range(1, repetitions + 1):
        project_name = f"verification-release-evidence-{os.getpid()}-{repetition}"
        context = ComposeContext(
            compose_file=compose_file,
            project_name=project_name,
            database_url=database_url,
            grader_url=grader_url,
            languagetool_health_url=languagetool_health_url,
        )
        repetition_report, discovered_environment = _run_repetition(context, repetition)
        repetition_reports.append(repetition_report)
        for key, value in discovered_environment.items():
            environment.setdefault(key, value)

    succeeded = all(item.get("status") == "succeeded" for item in repetition_reports)
    cleanup_succeeded = all(
        isinstance(item.get("cleanup"), Mapping) and item["cleanup"].get("status") == "succeeded"  # type: ignore[index]
        for item in repetition_reports
    )
    report: dict[str, object] = {
        "report_version": REPORT_VERSION,
        "scenario_catalog_version": SCENARIO_CATALOG_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_revision": _source_revision(),
        "contracts": {
            "validator_version": BUDGET_AWARE_VALIDATOR_VERSION,
            "ruleset_version": BUDGET_AWARE_RULESET_VERSION,
            "capacity_version": VERIFICATION_CAPACITY_RULESET_VERSION,
            "budget_version": VERIFICATION_BUDGET_RULESET_VERSION,
        },
        "protocol": {
            "repetitions": repetitions,
            "database": "postgresql",
            "grader": "real_http_service",
            "language_dependency": "real_languagetool_service",
            "isolation": "unique_compose_project_and_volume_per_repetition",
            "cleanup_policy": "docker_compose_down_with_volumes",
        },
        "environment": environment,
        "summary": {
            "repetition_count": len(repetition_reports),
            "scenario_count": sum(
                len(item.get("scenarios", []))
                for item in repetition_reports
                if isinstance(item.get("scenarios"), list)
            ),
            "all_repetitions_succeeded": succeeded,
            "all_cleanup_succeeded": cleanup_succeeded,
        },
        "repetitions": repetition_reports,
    }
    assert_deidentified_evidence(report)
    paths = write_report(report, output_dir)
    return report, paths


def _run_repetition(
    context: ComposeContext,
    repetition: int,
) -> tuple[dict[str, object], dict[str, object]]:
    report: dict[str, object] = {
        "repetition": repetition,
        "status": "pending",
        "failure_code": None,
        "scenarios": [],
        "cleanup": {"status": "pending"},
    }
    environment: dict[str, object] = {}
    stage = "compose_start"
    try:
        _compose(
            context,
            "up",
            "--detach",
            "--build",
            "--wait",
            "--wait-timeout",
            "240",
            "postgres",
            "languagetool",
            "grader",
        )
        stage = "database_migration"
        _run_migrations(context.database_url)
        stage = "environment_capture"
        environment = _capture_service_environment(context)
        stage = "scenario_execution"
        with _session(context.database_url) as session:
            scenarios = [
                _capacity_gate_scenario(session),
                _language_recovery_scenario(session, context),
            ]
            report["scenarios"] = scenarios
            if not all(item.get("passed") is True for item in scenarios):
                raise ProductRegression("representative_scenario_failed")
        report["status"] = "succeeded"
    except ProductRegression as error:
        report["status"] = "product_regression"
        report["failure_code"] = error.code
    except Exception:
        report["status"] = "infrastructure_failure"
        report["failure_code"] = f"{stage}_failed"
    finally:
        cleanup = _cleanup(context)
        report["cleanup"] = cleanup
        if cleanup["status"] != "succeeded" and report["status"] == "succeeded":
            report["status"] = "infrastructure_failure"
            report["failure_code"] = "cleanup_failed"
    return report, environment


def _capacity_gate_scenario(session: Session) -> dict[str, object]:
    candidate = _base_candidate("E3")
    candidate["release_evidence_padding"] = "x" * (MAX_CANDIDATE_BYTES + 4096)
    capacity = evaluate_verification_capacity(candidate)
    _require(capacity.blocked, "capacity_fixture_not_blocked")
    _require(capacity.load_bucket == "oversize", "capacity_fixture_wrong_bucket")
    case = BenchmarkCase(
        case_id="capacity-candidate-bytes",
        question_type="E3",
        load_bucket="oversize",  # type: ignore[arg-type]
        policy_version="1",
        expected_status="blocked",
        candidate_bytes=capacity.observations["candidate_bytes"],
        candidate=candidate,
    )
    draft = _create_synthetic_draft(session, case=case, ordinal=1)
    session.commit()
    revision = _revision(session, draft)
    versions_before = _question_version_count(session)
    run = run_budget_aware_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=HttpGraderClient("http://127.0.0.1:9"),
    )
    session.commit()
    versions_after = _question_version_count(session)
    finding_codes = _finding_codes(run)
    capacity_signal = run.feature_summary_json.get("verification_capacity_signal")
    passed = (
        run.status.value == "blocked"
        and "candidate_capacity_limit_exceeded" in finding_codes
        and versions_after == versions_before
        and isinstance(capacity_signal, dict)
        and capacity_signal.get("load_bucket") == "oversize"
    )
    return {
        "scenario_id": "capacity_candidate_bytes",
        "expected_status": "blocked",
        "actual_status": run.status.value,
        "finding_codes": finding_codes,
        "question_version_delta": versions_after - versions_before,
        "external_dependency_guard": "unreachable_grader",
        "capacity_bucket": (
            capacity_signal.get("load_bucket") if isinstance(capacity_signal, dict) else None
        ),
        "passed": passed,
    }


def _language_recovery_scenario(
    session: Session,
    context: ComposeContext,
) -> dict[str, object]:
    candidate = _base_candidate("E3")
    candidate["difficulty"] = 0.2
    capacity = evaluate_verification_capacity(candidate)
    _require(not capacity.blocked, "language_fixture_blocked")
    case = BenchmarkCase(
        case_id="language-dependency-recovery",
        question_type="E3",
        load_bucket="small",
        policy_version="1",
        expected_status="passed",
        candidate_bytes=capacity.observations["candidate_bytes"],
        candidate=candidate,
    )
    draft = _create_synthetic_draft(session, case=case, ordinal=2)
    session.commit()
    revision = _revision(session, draft)
    versions_before = _question_version_count(session)
    grader = HttpGraderClient(context.grader_url)

    _compose(context, "stop", "languagetool")
    outage_run = run_budget_aware_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=grader,
    )
    session.commit()
    outage_snapshot = _run_snapshot(outage_run)

    _compose(context, "start", "languagetool")
    _wait_for_http(context.languagetool_health_url, timeout_seconds=90)
    _compose(context, "restart", "grader")
    _wait_for_http(f"{context.grader_url}/health", timeout_seconds=90)
    recovery_run = run_budget_aware_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=grader,
    )
    session.commit()
    versions_after = _question_version_count(session)

    session.expire_all()
    persisted_outage = session.get(GenerationValidationRun, outage_run.id)
    _require(persisted_outage is not None, "outage_run_missing")
    outage_immutable = _run_snapshot(persisted_outage) == outage_snapshot
    recovery_budget = recovery_run.feature_summary_json.get("verification_budget_signal")
    passed = (
        outage_run.status.value == "blocked"
        and recovery_run.status.value == "passed"
        and outage_run.id != recovery_run.id
        and outage_immutable
        and versions_after == versions_before
        and isinstance(recovery_budget, dict)
        and recovery_budget.get("status") == "completed"
    )
    return {
        "scenario_id": "language_dependency_recovery",
        "outage_status": outage_run.status.value,
        "outage_finding_codes": _finding_codes(outage_run),
        "recovery_status": recovery_run.status.value,
        "recovery_finding_codes": _finding_codes(recovery_run),
        "old_run_immutable": outage_immutable,
        "fresh_budget_completed": (
            recovery_budget.get("status") == "completed"
            if isinstance(recovery_budget, dict)
            else False
        ),
        "question_version_delta": versions_after - versions_before,
        "passed": passed,
    }


def _capture_service_environment(context: ComposeContext) -> dict[str, object]:
    with _session(context.database_url) as session:
        postgres_version = session.execute(text("SHOW server_version")).scalar_one()
    return {
        "python_version": platform.python_version(),
        "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
        "postgres_version": str(postgres_version),
        "postgres_image_id": _service_image_id(context, "postgres"),
        "grader_image_id": _service_image_id(context, "grader"),
        "languagetool_image_id": _service_image_id(context, "languagetool"),
    }


def runtime_environment() -> dict[str, object]:
    return {
        "python_version": platform.python_version(),
        "os": platform.system() or "unknown",
        "architecture": platform.machine() or "unknown",
        "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
    }


def render_markdown(report: Mapping[str, object]) -> str:
    summary = report.get("summary")
    contracts = report.get("contracts")
    repetitions = report.get("repetitions")
    if not isinstance(summary, Mapping) or not isinstance(contracts, Mapping):
        raise ValueError("release evidence metadata is invalid")
    if not isinstance(repetitions, list):
        raise ValueError("release evidence repetitions are invalid")
    lines = [
        f"# Verification release evidence: {report['report_version']}",
        "",
        "## Summary",
        "",
        f"- Source revision: `{report['source_revision']}`",
        f"- Repetitions: {summary['repetition_count']}",
        f"- Scenarios: {summary['scenario_count']}",
        f"- All repetitions succeeded: {summary['all_repetitions_succeeded']}",
        f"- All cleanup succeeded: {summary['all_cleanup_succeeded']}",
        "",
        "## Contracts",
        "",
        f"- Validator: `{contracts['validator_version']}`",
        f"- Ruleset: `{contracts['ruleset_version']}`",
        f"- Capacity: `{contracts['capacity_version']}`",
        f"- Budget: `{contracts['budget_version']}`",
        "",
        "## Scenarios",
        "",
        "| Repetition | Scenario | Status | Recovery | Versions created | Passed |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    for repetition in repetitions:
        if not isinstance(repetition, Mapping):
            raise ValueError("release evidence repetition is invalid")
        scenarios = repetition.get("scenarios")
        if not isinstance(scenarios, list):
            continue
        for scenario in scenarios:
            if not isinstance(scenario, Mapping):
                raise ValueError("release evidence scenario is invalid")
            status = scenario.get("actual_status", scenario.get("outage_status", "n/a"))
            recovery = scenario.get("recovery_status", "n/a")
            lines.append(
                "| {repetition} | {scenario_id} | {status} | {recovery} | {delta} | {passed} |".format(
                    repetition=repetition["repetition"],
                    scenario_id=scenario["scenario_id"],
                    status=status,
                    recovery=recovery,
                    delta=scenario.get("question_version_delta", 0),
                    passed=scenario.get("passed", False),
                )
            )
    lines.extend(
        [
            "",
            "## Cleanup",
            "",
            "| Repetition | Status | Containers removed | Volumes removed |",
            "| ---: | --- | --- | --- |",
        ]
    )
    for repetition in repetitions:
        if not isinstance(repetition, Mapping) or not isinstance(
            repetition.get("cleanup"), Mapping
        ):
            continue
        cleanup = repetition["cleanup"]
        lines.append(
            "| {repetition} | {status} | {containers} | {volumes} |".format(
                repetition=repetition["repetition"],
                status=cleanup["status"],
                containers=cleanup.get("containers_removed", False),
                volumes=cleanup.get("volumes_removed", False),
            )
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: Mapping[str, object], output_dir: Path) -> ReportPaths:
    assert_deidentified_evidence(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    markdown_path = output_dir / MARKDOWN_FILENAME
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return ReportPaths(json_path=json_path, markdown_path=markdown_path)


def assert_deidentified_evidence(value: object, *, path: str = "evidence") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string key")
            normalized = key.casefold()
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise ValueError(f"{path} contains forbidden field: {key}")
            assert_deidentified_evidence(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_deidentified_evidence(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and ("http://" in value or "https://" in value):
        raise ValueError(f"{path} contains a network location")


def _session(database_url: str) -> Session:
    engine = create_engine(database_url, pool_pre_ping=True)
    return Session(engine)


def _revision(session: Session, draft: GeneratedQuestionDraft) -> GeneratedQuestionDraftRevision:
    revision = session.get(GeneratedQuestionDraftRevision, draft.current_revision_id)
    if revision is None:
        raise ProductRegression("draft_revision_missing")
    return revision


def _question_version_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(QuestionVersion)) or 0)


def _finding_codes(run: GenerationValidationRun) -> list[str]:
    return sorted(finding.code for finding in run.findings)


def _run_snapshot(run: GenerationValidationRun) -> dict[str, object]:
    return {
        "status": run.status.value,
        "finding_codes": _finding_codes(run),
        "validator_version": run.validator_version,
        "ruleset_version": run.ruleset_version,
        "feature_summary": deepcopy(run.feature_summary_json),
    }


def _compose(context: ComposeContext, *arguments: str) -> None:
    subprocess.run(
        [*context.command_prefix, *arguments],
        check=True,
        env=os.environ.copy(),
    )


def _run_migrations(database_url: str) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "apps/api/alembic.ini", "upgrade", "head"],
        check=True,
        env=environment,
    )


def _wait_for_http(target: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(target, timeout=3) as response:  # noqa: S310
                if 200 <= response.status < 300:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("dependency health check did not recover")


def _service_image_id(context: ComposeContext, service: str) -> str:
    container = subprocess.run(
        [*context.command_prefix, "ps", "--quiet", service],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if not container:
        raise RuntimeError("release evidence service container is missing")
    return subprocess.run(
        ["docker", "inspect", "--format", "{{.Image}}", container],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _cleanup(context: ComposeContext) -> dict[str, object]:
    command_succeeded = True
    try:
        _compose(context, "down", "--volumes", "--remove-orphans", "--timeout", "10")
    except Exception:
        command_succeeded = False
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={context.project_name}",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.split()
    volumes = subprocess.run(
        [
            "docker",
            "volume",
            "ls",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={context.project_name}",
        ],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.split()
    containers_removed = not containers
    volumes_removed = not volumes
    return {
        "status": (
            "succeeded"
            if command_succeeded and containers_removed and volumes_removed
            else "failed"
        ),
        "containers_removed": containers_removed,
        "volumes_removed": volumes_removed,
    }


def _source_revision() -> str:
    configured = os.environ.get("RELEASE_EVIDENCE_SOURCE_REVISION") or os.environ.get("GITHUB_SHA")
    if configured:
        return configured
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() or "unknown"


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ProductRegression(code)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("infra/release-evidence/compose.yaml"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/verification-release-evidence"),
    )
    parser.add_argument("--repetitions", type=int, default=DEFAULT_REPETITIONS)
    parser.add_argument(
        "--database-url",
        default=os.environ.get("RELEASE_EVIDENCE_DATABASE_URL", DEFAULT_DATABASE_URL),
    )
    parser.add_argument(
        "--grader-url",
        default=os.environ.get("RELEASE_EVIDENCE_GRADER_URL", DEFAULT_GRADER_URL),
    )
    parser.add_argument(
        "--languagetool-health-url",
        default=os.environ.get(
            "RELEASE_EVIDENCE_LANGUAGETOOL_HEALTH_URL",
            DEFAULT_LANGUAGETOOL_HEALTH_URL,
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    report, paths = run_release_evidence(
        compose_file=arguments.compose_file,
        output_dir=arguments.output_dir,
        repetitions=arguments.repetitions,
        database_url=arguments.database_url,
        grader_url=arguments.grader_url,
        languagetool_health_url=arguments.languagetool_health_url,
    )
    print(paths.json_path)
    print(paths.markdown_path)
    summary = report["summary"]
    if not isinstance(summary, Mapping):
        return 1
    return 0 if summary.get("all_repetitions_succeeded") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
