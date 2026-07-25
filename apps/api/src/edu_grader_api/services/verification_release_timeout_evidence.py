"""Real-service release evidence for stable verification dependency read timeouts."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
from threading import Lock, Thread
import time
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from ..models import GeneratedQuestionDraft, GeneratedQuestionDraftRevision
from ..settings import settings
from . import verification_release_evidence as base
from .budget_aware_verification import (
    BUDGET_AWARE_RULESET_VERSION,
    BUDGET_AWARE_VALIDATOR_VERSION,
    run_budget_aware_candidate_verification,
)
from .grader import HttpGraderClient
from .verification_budget import VERIFICATION_BUDGET_RULESET_VERSION
from .verification_capacity import (
    VERIFICATION_CAPACITY_RULESET_VERSION,
    evaluate_verification_capacity,
)
from .verification_performance import (
    BenchmarkCase,
    _base_candidate,
    _create_synthetic_draft,
)

REPORT_VERSION = base.REPORT_VERSION
SCENARIO_CATALOG_VERSION = 2
DEFAULT_REPETITIONS = base.DEFAULT_REPETITIONS
DEFAULT_DATABASE_URL = base.DEFAULT_DATABASE_URL
DEFAULT_GRADER_URL = base.DEFAULT_GRADER_URL
DEFAULT_LANGUAGETOOL_HEALTH_URL = base.DEFAULT_LANGUAGETOOL_HEALTH_URL

DependencyKind = Literal["normalizer", "grader", "similarity"]
ProxyMode = Literal["stall", "forward"]

_EXPECTED_TIMEOUT_FINDING: Mapping[DependencyKind, str] = {
    "normalizer": "normalizer_timeout",
    "grader": "grader_timeout",
    "similarity": "similarity_timeout",
}
_SCENARIO_ID: Mapping[DependencyKind, str] = {
    "normalizer": "normalizer_read_timeout_recovery",
    "grader": "grader_read_timeout_recovery",
    "similarity": "similarity_read_timeout_recovery",
}


class _FaultProxyHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True
    proxy: FaultInjectingGraderProxy


class _FaultProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:  # noqa: N802
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        mode = self.server.proxy._record_call()  # type: ignore[attr-defined]
        self.close_connection = True
        if mode == "stall":
            time.sleep(self.server.proxy.stall_seconds)  # type: ignore[attr-defined]
            return

        proxy = self.server.proxy  # type: ignore[attr-defined]
        try:
            response = httpx.post(
                f"{proxy.upstream_base}{self.path}",
                content=body,
                headers={
                    "Content-Type": self.headers.get(
                        "Content-Type",
                        "application/json",
                    ),
                },
                timeout=proxy.forward_timeout_seconds,
            )
        except httpx.HTTPError:
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        response_body = response.content
        self.send_response(response.status_code)
        content_type = response.headers.get("Content-Type")
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(response_body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(response_body)
        except BrokenPipeError:
            return

    def log_message(self, _format: str, *args: object) -> None:
        return


@dataclass(slots=True)
class FaultInjectingGraderProxy:
    """Local proxy that either forwards a Grader request or withholds its response."""

    upstream_base: str
    stall_seconds: float
    forward_timeout_seconds: float = 30.0
    _mode: ProxyMode = field(init=False, default="forward")
    _counts: dict[ProxyMode, int] = field(
        init=False,
        default_factory=lambda: {"stall": 0, "forward": 0},
    )
    _lock: Lock = field(init=False, default_factory=Lock)
    _server: _FaultProxyHTTPServer | None = field(init=False, default=None)
    _thread: Thread | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.upstream_base = self.upstream_base.rstrip("/")
        if self.stall_seconds <= 0 or self.forward_timeout_seconds <= 0:
            raise ValueError("fault proxy timeouts must be positive")

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("fault proxy is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FaultInjectingGraderProxy:
        if self._server is not None:
            raise RuntimeError("fault proxy is already running")
        server = _FaultProxyHTTPServer(("127.0.0.1", 0), _FaultProxyHandler)
        server.proxy = self
        thread = Thread(
            target=server.serve_forever,
            name="verification-fault-proxy",
            daemon=True,
        )
        thread.start()
        self._server = server
        self._thread = thread
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def set_mode(self, mode: ProxyMode) -> None:
        with self._lock:
            self._mode = mode

    def reset_counts(self) -> None:
        with self._lock:
            self._counts = {"stall": 0, "forward": 0}

    def call_counts(self) -> dict[ProxyMode, int]:
        with self._lock:
            return dict(self._counts)

    def _record_call(self) -> ProxyMode:
        with self._lock:
            mode = self._mode
            self._counts[mode] += 1
            return mode


def run_release_evidence(
    *,
    compose_file: Path,
    output_dir: Path,
    repetitions: int = DEFAULT_REPETITIONS,
    database_url: str = DEFAULT_DATABASE_URL,
    grader_url: str = DEFAULT_GRADER_URL,
    languagetool_health_url: str = DEFAULT_LANGUAGETOOL_HEALTH_URL,
) -> tuple[dict[str, object], base.ReportPaths]:
    if REPORT_VERSION != "verification-release-evidence-v1":
        raise RuntimeError("unsupported base release-evidence contract")
    if repetitions < 2:
        raise ValueError("release evidence requires at least two repetitions")
    if not compose_file.is_file():
        raise ValueError("release evidence compose file does not exist")

    repetition_reports: list[dict[str, object]] = []
    environment: dict[str, object] = base.runtime_environment()
    for repetition in range(1, repetitions + 1):
        context = base.ComposeContext(
            compose_file=compose_file,
            project_name=f"verification-release-evidence-{os.getpid()}-{repetition}",
            database_url=database_url,
            grader_url=grader_url,
            languagetool_health_url=languagetool_health_url,
        )
        repetition_report, discovered_environment = _run_repetition(context, repetition)
        repetition_reports.append(repetition_report)
        for key, value in discovered_environment.items():
            environment.setdefault(key, value)

    all_repetitions_succeeded = all(
        item.get("status") == "succeeded" for item in repetition_reports
    )
    all_cleanup_succeeded = all(
        isinstance(item.get("cleanup"), Mapping)
        and item["cleanup"].get("status") == "succeeded"  # type: ignore[index]
        for item in repetition_reports
    )
    report: dict[str, object] = {
        "report_version": REPORT_VERSION,
        "scenario_catalog_version": SCENARIO_CATALOG_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_revision": base._source_revision(),
        "contracts": {
            "validator_version": BUDGET_AWARE_VALIDATOR_VERSION,
            "ruleset_version": BUDGET_AWARE_RULESET_VERSION,
            "capacity_version": VERIFICATION_CAPACITY_RULESET_VERSION,
            "budget_version": VERIFICATION_BUDGET_RULESET_VERSION,
            "timeout_fault_version": "verification-dependency-read-timeout-v1",
        },
        "protocol": {
            "repetitions": repetitions,
            "database": "postgresql",
            "grader": "real_http_service",
            "language_dependency": "real_languagetool_service",
            "fault_injection": "local_response_stall_proxy",
            "timeout_dependencies": ["normalizer", "grader", "similarity"],
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
            "all_repetitions_succeeded": all_repetitions_succeeded,
            "all_cleanup_succeeded": all_cleanup_succeeded,
        },
        "repetitions": repetition_reports,
    }
    base.assert_deidentified_evidence(report)
    paths = base.write_report(report, output_dir)
    return report, paths


def _run_repetition(
    context: base.ComposeContext,
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
        base._compose(
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
        base._run_migrations(context.database_url)
        stage = "environment_capture"
        environment = base._capture_service_environment(context)
        stage = "scenario_execution"
        with base._session(context.database_url) as session:
            scenarios: list[dict[str, object]] = []
            _append_scenario(
                session,
                scenarios,
                "capacity_candidate_bytes",
                lambda: base._capacity_gate_scenario(session),
            )
            _append_scenario(
                session,
                scenarios,
                "language_dependency_recovery",
                lambda: base._language_recovery_scenario(session, context),
            )
            base._wait_for_http(f"{context.grader_url}/health", timeout_seconds=90)
            _warm_timeout_dependencies(context.grader_url)
            stall_seconds = float(settings.grader_request_timeout_seconds) + 1.0
            with FaultInjectingGraderProxy(
                context.grader_url,
                stall_seconds=stall_seconds,
                forward_timeout_seconds=max(stall_seconds * 2, 30.0),
            ) as proxy:
                for index, dependency in enumerate(
                    ("normalizer", "grader", "similarity"),
                    start=1,
                ):
                    scenario_id = _SCENARIO_ID[dependency]
                    _append_scenario(
                        session,
                        scenarios,
                        scenario_id,
                        lambda dependency=dependency, ordinal=(
                            repetition * 100 + index
                        ): _dependency_timeout_recovery_scenario(
                            session,
                            proxy=proxy,
                            dependency=dependency,
                            ordinal=ordinal,
                        ),
                    )
            report["scenarios"] = scenarios
            if not all(item.get("passed") is True for item in scenarios):
                raise base.ProductRegression("representative_scenario_failed")
        report["status"] = "succeeded"
    except base.ProductRegression as error:
        report["status"] = "product_regression"
        report["failure_code"] = error.code
    except Exception:
        report["status"] = "infrastructure_failure"
        report["failure_code"] = f"{stage}_failed"
    finally:
        cleanup = base._cleanup(context)
        report["cleanup"] = cleanup
        if cleanup["status"] != "succeeded" and report["status"] == "succeeded":
            report["status"] = "infrastructure_failure"
            report["failure_code"] = "cleanup_failed"
    return report, environment


def _append_scenario(
    session: Session,
    scenarios: list[dict[str, object]],
    scenario_id: str,
    callback: Callable[[], dict[str, object]],
) -> None:
    try:
        scenarios.append(callback())
    except Exception:
        session.rollback()
        scenarios.append(
            {
                "scenario_id": scenario_id,
                "failure_code": f"{scenario_id}_execution_failed",
                "passed": False,
            }
        )


def _warm_timeout_dependencies(grader_url: str) -> None:
    grader = HttpGraderClient(grader_url)
    grader.normalize_math_answer(
        {"mathjson": ["Add", "x", 1], "variables": ["x"]}
    )
    grader.grade(
        "M1",
        {"expected": 4, "tolerance": 0},
        {"format": "text-v1", "text": "4"},
        policy_version="1",
    )
    grader.semantic_similarity(
        "Compute the exact numeric sum of two and two.",
        [
            (
                "Catalogue basalt columns beneath an aurora while observing "
                "distant seabird plumage."
            )
        ],
    )


def _dependency_timeout_recovery_scenario(
    session: Session,
    *,
    proxy: FaultInjectingGraderProxy,
    dependency: DependencyKind,
    ordinal: int,
) -> dict[str, object]:
    draft = _create_timeout_draft(session, dependency=dependency, ordinal=ordinal)
    session.commit()
    revision = base._revision(session, draft)
    versions_before = base._question_version_count(session)
    grader = HttpGraderClient(proxy.base_url)

    proxy.reset_counts()
    proxy.set_mode("stall")
    outage_run = run_budget_aware_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=grader,
    )
    session.commit()
    outage_counts = proxy.call_counts()
    outage_snapshot = base._run_snapshot(outage_run)

    proxy.reset_counts()
    proxy.set_mode("forward")
    recovery_run = run_budget_aware_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=grader,
    )
    session.commit()
    recovery_counts = proxy.call_counts()
    versions_after = base._question_version_count(session)

    session.expire_all()
    persisted_outage = session.get(base.GenerationValidationRun, outage_run.id)
    if persisted_outage is None:
        raise base.ProductRegression("dependency_timeout_run_missing")
    outage_immutable = base._run_snapshot(persisted_outage) == outage_snapshot
    outage_budget = outage_run.feature_summary_json.get("verification_budget_signal")
    recovery_budget = recovery_run.feature_summary_json.get(
        "verification_budget_signal"
    )
    outage_findings = base._finding_codes(outage_run)
    recovery_findings = base._finding_codes(recovery_run)
    expected_finding = _EXPECTED_TIMEOUT_FINDING[dependency]
    new_calls_after_timeout = max(outage_counts["stall"] - 1, 0)
    passed = (
        outage_run.status.value == "blocked"
        and expected_finding in outage_findings
        and isinstance(outage_budget, dict)
        and outage_budget.get("status") == "dependency_timeout"
        and outage_budget.get("terminal_dependency") == dependency
        and outage_counts["stall"] == 1
        and new_calls_after_timeout == 0
        and recovery_run.status.value == "passed"
        and expected_finding not in recovery_findings
        and isinstance(recovery_budget, dict)
        and recovery_budget.get("status") == "completed"
        and recovery_counts["forward"] > 0
        and outage_run.id != recovery_run.id
        and outage_immutable
        and versions_after == versions_before
    )
    return {
        "scenario_id": _SCENARIO_ID[dependency],
        "dependency": dependency,
        "fault_mode": "read_timeout",
        "outage_status": outage_run.status.value,
        "outage_finding_codes": outage_findings,
        "outage_call_bucket": _call_bucket(outage_counts["stall"]),
        "new_calls_after_timeout": new_calls_after_timeout,
        "recovery_status": recovery_run.status.value,
        "recovery_finding_codes": recovery_findings,
        "recovery_call_bucket": _call_bucket(recovery_counts["forward"]),
        "old_run_immutable": outage_immutable,
        "fresh_budget_completed": (
            recovery_budget.get("status") == "completed"
            if isinstance(recovery_budget, dict)
            else False
        ),
        "question_version_delta": versions_after - versions_before,
        "passed": passed,
    }


def _create_timeout_draft(
    session: Session,
    *,
    dependency: DependencyKind,
    ordinal: int,
) -> GeneratedQuestionDraft:
    question_type = "M2" if dependency == "normalizer" else "M1"
    candidate = _base_candidate(question_type)
    candidate["difficulty"] = 0.2
    if dependency == "similarity":
        candidate["prompt"] = "Compute the exact numeric sum of two and two."
    capacity = evaluate_verification_capacity(candidate)
    if capacity.blocked or capacity.load_bucket != "small":
        raise base.ProductRegression("dependency_timeout_fixture_invalid")
    case = BenchmarkCase(
        case_id=f"{dependency}-read-timeout-{ordinal}",
        question_type=question_type,
        load_bucket="small",
        policy_version=str(candidate["policy_version"]),
        expected_status="passed",
        candidate_bytes=capacity.observations["candidate_bytes"],
        candidate=candidate,
    )
    draft = _create_synthetic_draft(session, case=case, ordinal=ordinal)
    if dependency == "similarity":
        _create_similarity_peer(session, draft=draft, ordinal=ordinal + 1)
    return draft


def _create_similarity_peer(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    ordinal: int,
) -> None:
    candidate = deepcopy(draft.candidate_json)
    candidate["prompt"] = (
        "Catalogue basalt columns beneath an aurora while observing distant "
        "seabird plumage."
    )
    candidate["explanation"] = (
        "This synthetic peer exists only for duplicate comparison."
    )
    content_hash = f"{ordinal + 100_000:064x}"[-64:]
    peer = GeneratedQuestionDraft(
        job_id=draft.job_id,
        generation_attempt_id=draft.generation_attempt_id,
        ordinal=ordinal,
        content_hash=content_hash,
        candidate_json=candidate,
        teacher_state="pending_review",
    )
    session.add(peer)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=peer.current_revision_id,
            generated_question_draft_id=peer.id,
            revision_number=1,
            candidate_json=candidate,
            content_hash=content_hash,
        )
    )
    session.flush()


def _call_bucket(count: int) -> str:
    if count <= 0:
        return "none"
    if count == 1:
        return "single"
    return "multiple"


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
