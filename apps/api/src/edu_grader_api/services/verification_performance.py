"""Repeatable, de-identified performance reports for candidate verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter_ns
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ..models import (
    Base,
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    Role,
    Tenant,
    User,
)
from .budget_aware_verification import (
    BUDGET_AWARE_RULESET_VERSION,
    BUDGET_AWARE_VALIDATOR_VERSION,
    run_budget_aware_candidate_verification,
)
from .grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .questions import GradeResult
from .verification_budget import VERIFICATION_BUDGET_RULESET_VERSION
from .verification_capacity import (
    VERIFICATION_CAPACITY_RULESET_VERSION,
    evaluate_verification_capacity,
)

REPORT_VERSION = "verification-performance-v1"
MATRIX_VERSION = 1
DEFAULT_WARMUP_RUNS = 1
DEFAULT_MEASURED_RUNS = 5
DEFAULT_SEED = 119
JSON_FILENAME = f"{REPORT_VERSION}.json"
MARKDOWN_FILENAME = f"{REPORT_VERSION}.md"

QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"]
LoadBucket = Literal["small", "medium", "large"]

_QUESTION_TYPES: tuple[QuestionType, ...] = ("M1", "M2", "E1", "E2", "E3", "E4")
_LOAD_BUCKETS: tuple[LoadBucket, ...] = ("small", "medium", "large")
_PADDING_CHARACTERS: Mapping[LoadBucket, int] = {
    "small": 512,
    "medium": 20 * 1024,
    "large": 70 * 1024,
}
_FORBIDDEN_REPORT_KEY_FRAGMENTS = (
    "prompt",
    "reading_material",
    "expected_answer",
    "rule_json",
    "assertion",
    "request_payload",
    "exception",
    "internal_url",
)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    question_type: QuestionType
    load_bucket: LoadBucket
    policy_version: str
    expected_status: str
    candidate_bytes: int
    candidate: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReportPaths:
    json_path: Path
    markdown_path: Path


class DeterministicBenchmarkGrader:
    """Network-free Grader contract used only by the synthetic benchmark matrix."""

    _embedding = EmbeddingDependencyVersion(
        id="synthetic-benchmark-embedding",
        revision="v1",
        digest="sha256:synthetic-benchmark",
    )

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return _normalize_synthetic_mathjson(answer_json.get("mathjson"))

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        if question_type == "M1":
            return _grade_m1(rule_json, answer_json)
        if question_type == "M2":
            return _grade_m2(rule_json, answer_json)
        if question_type == "E2":
            return GradeResult("auto_accepted", 1, {}, "synthetic-benchmark-v1")
        if question_type == "E3":
            return GradeResult(
                "needs_review",
                0,
                {"feedback": []},
                "synthetic-benchmark-v1",
            )
        if question_type == "E4":
            points = rule_json.get("scoring_points")
            score = 0.0
            if isinstance(points, list) and points and isinstance(points[0], dict):
                value = points[0].get("score", 0)
                if not isinstance(value, bool) and isinstance(value, int | float):
                    score = float(value)
            return GradeResult("needs_review", score, {}, "synthetic-benchmark-v1")
        raise ValueError(f"unsupported synthetic benchmark question type: {question_type}")

    def semantic_similarity(
        self,
        query: str,
        comparisons: list[str],
    ) -> SemanticSimilarityResult:
        return SemanticSimilarityResult(
            scores=[0.0 for _ in comparisons],
            embedding=self._embedding,
        )


class SyntheticVerificationExecutor:
    """Execute the real production verification wrapper over synthetic SQLite data."""

    def __init__(self, cases: Iterable[BenchmarkCase]) -> None:
        self._engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self._engine)
        self._session = Session(self._engine)
        self._grader = DeterministicBenchmarkGrader()
        self._targets: dict[str, tuple[UUID, UUID]] = {}
        for index, case in enumerate(cases, start=1):
            draft = _create_synthetic_draft(
                self._session,
                case=case,
                ordinal=index,
            )
            self._targets[case.case_id] = (draft.id, draft.current_revision_id)
        self._session.commit()

    def __call__(self, case: BenchmarkCase) -> str:
        draft_id, revision_id = self._targets[case.case_id]
        draft = self._session.get(GeneratedQuestionDraft, draft_id)
        revision = self._session.get(GeneratedQuestionDraftRevision, revision_id)
        if draft is None or revision is None:
            raise RuntimeError("synthetic benchmark target is unavailable")
        run = run_budget_aware_candidate_verification(
            self._session,
            draft=draft,
            revision=revision,
            grader_client=self._grader,
        )
        status = run.status.value
        summary = dict(run.feature_summary_json)
        capacity_signal = summary.get("verification_capacity_signal")
        budget_signal = summary.get("verification_budget_signal")
        if run.validator_version != BUDGET_AWARE_VALIDATOR_VERSION:
            raise RuntimeError("unexpected benchmark validator version")
        if run.ruleset_version != BUDGET_AWARE_RULESET_VERSION:
            raise RuntimeError("unexpected benchmark ruleset version")
        if (
            not isinstance(capacity_signal, dict)
            or capacity_signal.get("load_bucket") != case.load_bucket
        ):
            raise RuntimeError("synthetic benchmark capacity bucket changed")
        if not isinstance(budget_signal, dict) or budget_signal.get("status") != "completed":
            raise RuntimeError("synthetic benchmark budget did not complete")
        self._session.rollback()
        return status

    def close(self) -> None:
        self._session.close()
        self._engine.dispose()

    def __enter__(self) -> SyntheticVerificationExecutor:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def build_benchmark_cases() -> tuple[BenchmarkCase, ...]:
    cases: list[BenchmarkCase] = []
    for question_type in _QUESTION_TYPES:
        for load_bucket in _LOAD_BUCKETS:
            candidate = _synthetic_candidate(question_type, load_bucket)
            capacity = evaluate_verification_capacity(candidate)
            if capacity.blocked or capacity.load_bucket != load_bucket:
                raise RuntimeError(
                    f"invalid synthetic matrix bucket: {question_type}-{load_bucket}"
                )
            cases.append(
                BenchmarkCase(
                    case_id=f"{question_type}-{load_bucket}",
                    question_type=question_type,
                    load_bucket=load_bucket,
                    policy_version=str(candidate["policy_version"]),
                    expected_status="passed",
                    candidate_bytes=capacity.observations["candidate_bytes"],
                    candidate=candidate,
                )
            )
    return tuple(cases)


def percentile_r7(values: Iterable[int | float], percentile: float) -> float:
    """Return an R-7 linearly interpolated percentile."""

    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one sample")
    if not math.isfinite(percentile) or percentile < 0 or percentile > 100:
        raise ValueError("percentile must be between 0 and 100")
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def run_benchmark(
    cases: Iterable[BenchmarkCase],
    executor: Callable[[BenchmarkCase], str],
    *,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    seed: int = DEFAULT_SEED,
    clock_ns: Callable[[], int] = perf_counter_ns,
    environment: Mapping[str, object] | None = None,
    generated_at_utc: str | None = None,
    source_revision: str | None = None,
) -> dict[str, object]:
    if warmup_runs < 0:
        raise ValueError("warmup runs cannot be negative")
    if measured_runs <= 0:
        raise ValueError("measured runs must be positive")

    ordered_cases = list(cases)
    if not ordered_cases:
        raise ValueError("benchmark matrix cannot be empty")
    random.Random(seed).shuffle(ordered_cases)

    case_reports: list[dict[str, object]] = []
    total_failures = 0
    for case in ordered_cases:
        for _ in range(warmup_runs):
            executor(case)

        durations_ns: list[int] = []
        status_counts: Counter[str] = Counter()
        failure_count = 0
        for _ in range(measured_runs):
            started = clock_ns()
            try:
                status = executor(case)
            except Exception:
                status = "execution_error"
            finished = clock_ns()
            elapsed = finished - started
            if elapsed < 0:
                raise RuntimeError("benchmark clock moved backwards")
            durations_ns.append(elapsed)
            status_counts[status] += 1
            if status != case.expected_status:
                failure_count += 1

        total_failures += failure_count
        total_seconds = sum(durations_ns) / 1_000_000_000
        throughput = measured_runs / total_seconds if total_seconds > 0 else 0.0
        case_reports.append(
            {
                "case_id": case.case_id,
                "question_type": case.question_type,
                "load_bucket": case.load_bucket,
                "policy_version": case.policy_version,
                "candidate_bytes": case.candidate_bytes,
                "expected_status": case.expected_status,
                "sample_count": measured_runs,
                "failure_count": failure_count,
                "status_counts": dict(sorted(status_counts.items())),
                "latency_ms": {
                    "minimum": _milliseconds(min(durations_ns)),
                    "p50": _milliseconds(percentile_r7(durations_ns, 50)),
                    "p95": _milliseconds(percentile_r7(durations_ns, 95)),
                    "p99": _milliseconds(percentile_r7(durations_ns, 99)),
                    "maximum": _milliseconds(max(durations_ns)),
                },
                "throughput_cases_per_second": round(throughput, 3),
            }
        )

    case_reports.sort(key=lambda item: str(item["case_id"]))
    report = {
        "report_version": REPORT_VERSION,
        "matrix_version": MATRIX_VERSION,
        "matrix_digest": _matrix_digest(ordered_cases),
        "generated_at_utc": generated_at_utc or datetime.now(UTC).isoformat(),
        "source_revision": source_revision or _source_revision(),
        "contracts": {
            "validator_version": BUDGET_AWARE_VALIDATOR_VERSION,
            "ruleset_version": BUDGET_AWARE_RULESET_VERSION,
            "capacity_version": VERIFICATION_CAPACITY_RULESET_VERSION,
            "budget_version": VERIFICATION_BUDGET_RULESET_VERSION,
        },
        "protocol": {
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "concurrency": 1,
            "seed": seed,
            "clock": "perf_counter_ns",
            "percentile_method": "R-7 linear interpolation",
            "outlier_policy": "none",
            "failure_policy": "retain every measured sample",
        },
        "environment": dict(environment or runtime_environment()),
        "summary": {
            "case_count": len(case_reports),
            "sample_count": len(case_reports) * measured_runs,
            "failure_count": total_failures,
            "all_cases_succeeded": total_failures == 0,
        },
        "cases": case_reports,
    }
    assert_deidentified_report(report)
    return report


def generate_production_report(
    *,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    seed: int = DEFAULT_SEED,
) -> dict[str, object]:
    cases = build_benchmark_cases()
    with SyntheticVerificationExecutor(cases) as executor:
        return run_benchmark(
            cases,
            executor,
            warmup_runs=warmup_runs,
            measured_runs=measured_runs,
            seed=seed,
        )


def runtime_environment() -> dict[str, object]:
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "os": platform.system() or "unknown",
        "os_release": platform.release() or "unknown",
        "architecture": platform.machine() or "unknown",
        "cpu_model": _cpu_model(),
        "cpu_count": os.cpu_count(),
        "runner": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
        "runner_os": os.environ.get("RUNNER_OS", platform.system() or "unknown"),
        "runner_arch": os.environ.get("RUNNER_ARCH", platform.machine() or "unknown"),
    }


def render_markdown(report: Mapping[str, object]) -> str:
    summary = report["summary"]
    protocol = report["protocol"]
    contracts = report["contracts"]
    environment = report["environment"]
    cases = report["cases"]
    if not all(isinstance(value, Mapping) for value in (summary, protocol, contracts, environment)):
        raise ValueError("performance report metadata is invalid")
    if not isinstance(cases, list):
        raise ValueError("performance report cases are invalid")

    lines = [
        f"# Verification performance report: {report['report_version']}",
        "",
        "## Summary",
        "",
        f"- Matrix: `{report['matrix_version']}` / `{report['matrix_digest']}`",
        f"- Source revision: `{report['source_revision']}`",
        f"- Cases: {summary['case_count']}",
        f"- Samples: {summary['sample_count']}",
        f"- Failures: {summary['failure_count']}",
        "",
        "## Protocol",
        "",
        f"- Warmups per case: {protocol['warmup_runs']}",
        f"- Measured runs per case: {protocol['measured_runs']}",
        f"- Concurrency: {protocol['concurrency']}",
        f"- Percentiles: {protocol['percentile_method']}",
        f"- Outliers: {protocol['outlier_policy']}",
        "",
        "## Contracts",
        "",
        f"- Validator: `{contracts['validator_version']}`",
        f"- Ruleset: `{contracts['ruleset_version']}`",
        f"- Capacity: `{contracts['capacity_version']}`",
        f"- Budget: `{contracts['budget_version']}`",
        "",
        "## Results",
        "",
        "| Case | Type | Bucket | Bytes | Samples | Failures | P50 ms | P95 ms | P99 ms | Cases/s |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in cases:
        if not isinstance(item, Mapping) or not isinstance(item.get("latency_ms"), Mapping):
            raise ValueError("performance case result is invalid")
        latency = item["latency_ms"]
        lines.append(
            "| {case_id} | {question_type} | {load_bucket} | {candidate_bytes} | "
            "{sample_count} | {failure_count} | {p50} | {p95} | {p99} | {throughput} |".format(
                case_id=item["case_id"],
                question_type=item["question_type"],
                load_bucket=item["load_bucket"],
                candidate_bytes=item["candidate_bytes"],
                sample_count=item["sample_count"],
                failure_count=item["failure_count"],
                p50=latency["p50"],
                p95=latency["p95"],
                p99=latency["p99"],
                throughput=item["throughput_cases_per_second"],
            )
        )
    lines.extend(
        [
            "",
            "## Environment",
            "",
            "| Field | Value |",
            "| --- | --- |",
        ]
    )
    for key, value in sorted(environment.items()):
        lines.append(f"| {key} | {value} |")
    lines.append("")
    return "\n".join(lines)


def write_report(report: Mapping[str, object], output_dir: Path) -> ReportPaths:
    assert_deidentified_report(report)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / JSON_FILENAME
    markdown_path = output_dir / MARKDOWN_FILENAME
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return ReportPaths(json_path=json_path, markdown_path=markdown_path)


def assert_deidentified_report(value: object, *, path: str = "report") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} contains a non-string key")
            normalized = key.casefold()
            if any(fragment in normalized for fragment in _FORBIDDEN_REPORT_KEY_FRAGMENTS):
                raise ValueError(f"{path} contains forbidden report field: {key}")
            assert_deidentified_report(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            assert_deidentified_report(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and ("http://" in value or "https://" in value):
        raise ValueError(f"{path} contains a URL")


def _synthetic_candidate(question_type: QuestionType, load_bucket: LoadBucket) -> dict[str, object]:
    candidate = _base_candidate(question_type)
    candidate["objective_revision_id"] = "00000000-0000-0000-0000-000000000000"
    candidate["difficulty"] = 0.2
    candidate["knowledge_point"] = "synthetic benchmark objective"
    candidate["benchmark_payload_padding"] = "x" * _PADDING_CHARACTERS[load_bucket]
    return candidate


def _base_candidate(question_type: QuestionType) -> dict[str, object]:
    if question_type == "M1":
        return {
            "question_type": "M1",
            "policy_version": "1",
            "prompt": "Compute two plus two.",
            "rule_json": {"expected": 4, "tolerance": 0},
            "explanation": "Add the values. Final answer: 4",
            "verification_assertions": {
                "final_answer_text": "4",
                "final_answer_mathjson": None,
                "declared_max_score": 1,
            },
        }
    if question_type == "M2":
        return {
            "question_type": "M2",
            "policy_version": "2",
            "prompt": "Write x plus one in expanded form.",
            "rule_json": {
                "expected": ["Add", "x", 1],
                "variables": ["x"],
                "required_form": "expanded",
                "max_score": 1,
            },
            "explanation": "The expression is expanded. Final answer: x + 1",
            "verification_assertions": {
                "final_answer_text": "x + 1",
                "final_answer_mathjson": '["Add","x",1]',
                "declared_max_score": 1,
            },
        }
    if question_type == "E1":
        return {
            "question_type": "E1",
            "policy_version": "2",
            "prompt": "Select the word blue.",
            "rule_json": {"accepted_answers": ["blue"]},
            "explanation": "Choose the matching word.",
        }
    if question_type == "E2":
        return {
            "question_type": "E2",
            "policy_version": "1",
            "prompt": "Use the past tense of go.",
            "rule_json": {
                "lemma": "go",
                "accepted_forms": ["went"],
                "constraints": {"tense": "past"},
            },
            "explanation": "The past-tense form is went.",
        }
    if question_type == "E3":
        return {
            "question_type": "E3",
            "policy_version": "1",
            "prompt": "Write one sentence about a journey.",
            "rule_json": {
                "grammar_feedback_required": True,
                "accepted_answers": ["I travelled by train."],
                "max_score": 1,
            },
            "explanation": "Use a complete sentence.",
        }
    return {
        "question_type": "E4",
        "policy_version": "2",
        "prompt": "Read the passage and state why the group was late.",
        "reading_material": "The bridge was closed, so the group arrived late.",
        "rule_json": {
            "max_score": 1,
            "similarity_threshold": 0.78,
            "scoring_points": [
                {
                    "id": "reason",
                    "evidence_phrases": ["bridge was closed"],
                    "score": 1,
                }
            ],
        },
        "explanation": "The passage states the reason for the delay.",
    }


def _create_synthetic_draft(
    session: Session,
    *,
    case: BenchmarkCase,
    ordinal: int,
) -> GeneratedQuestionDraft:
    subject = "mathematics" if case.question_type.startswith("M") else "english"
    tenant = Tenant(slug=f"benchmark-{uuid4()}", name="Synthetic Benchmark")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject=str(uuid4()),
        display_name="Synthetic Teacher",
        work_email=f"benchmark-{uuid4()}@example.test",
    )
    source = CurriculumSourceRecord(
        issuer="Synthetic Board",
        title="Synthetic curriculum",
        canonical_url="https://curriculum.example.test/synthetic",
        version_label="v1",
    )
    profile = CurriculumProfile(
        code=f"benchmark-{uuid4()}",
        name="Synthetic Benchmark Profile",
        jurisdiction="synthetic",
        version_label="v1",
        status=CurriculumProfileStatus.ACTIVE,
        source_record=source,
    )
    grade = CurriculumGradeMapping(
        profile=profile,
        internal_level="G5",
        external_label="Grade 5",
        position=5,
    )
    objective = CurriculumObjective(
        profile=profile,
        grade_mapping=grade,
        code=f"SYNTHETIC-{uuid4()}",
        subject=subject,
        domain="synthetic",
        status=CurriculumProfileStatus.ACTIVE,
    )
    objective_revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Synthetic benchmark objective.",
        source_locator="synthetic-v1",
        allowed_question_types=[case.question_type],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=CurriculumRevisionStatus.ACTIVE,
    )
    session.add_all([teacher, objective_revision])
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_profile_id=profile.id,
        curriculum_objective_revision_id=objective_revision.id,
        grade="Grade 5",
        subject=subject,
        distribution_json={"question_types": [case.question_type]},
        idempotency_key=str(uuid4()),
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=1,
        prompt_version="generator-v3",
    )
    session.add(job)
    session.flush()
    attempt = GenerationAttempt(
        job_id=job.id,
        attempt_number=1,
        provider_name="synthetic",
        model_version="synthetic-v1",
        prompt_version="generator-v3",
        status="succeeded",
    )
    session.add(attempt)
    session.flush()
    candidate = deepcopy(case.candidate)
    candidate["objective_revision_id"] = str(objective_revision.id)
    actual_capacity = evaluate_verification_capacity(candidate)
    if actual_capacity.load_bucket != case.load_bucket:
        raise RuntimeError("synthetic candidate changed capacity bucket")
    content_hash = f"{ordinal:064x}"[-64:]
    draft = GeneratedQuestionDraft(
        job_id=job.id,
        generation_attempt_id=attempt.id,
        ordinal=ordinal,
        content_hash=content_hash,
        candidate_json=candidate,
        teacher_state="pending_review",
    )
    session.add(draft)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=draft.current_revision_id,
            generated_question_draft_id=draft.id,
            revision_number=1,
            candidate_json=candidate,
            content_hash=content_hash,
        )
    )
    session.flush()
    return draft


def _grade_m1(
    rule_json: dict[str, object],
    answer_json: dict[str, object],
) -> GradeResult:
    expected = rule_json.get("expected")
    tolerance = rule_json.get("tolerance", 0)
    text = answer_json.get("text")
    accepted = False
    if (
        not isinstance(expected, bool)
        and isinstance(expected, int | float)
        and not isinstance(tolerance, bool)
        and isinstance(tolerance, int | float)
        and isinstance(text, str)
        and text
    ):
        try:
            accepted = abs(float(text) - float(expected)) <= float(tolerance)
        except ValueError:
            accepted = False
    return GradeResult(
        "auto_accepted" if accepted else "auto_rejected",
        1 if accepted else 0,
        {},
        "synthetic-benchmark-v1",
    )


def _grade_m2(
    rule_json: dict[str, object],
    answer_json: dict[str, object],
) -> GradeResult:
    accepted = answer_json.get("mathjson") == rule_json.get("expected")
    maximum = rule_json.get("max_score", 1)
    score = float(maximum) if accepted and isinstance(maximum, int | float) else 0.0
    return GradeResult(
        "auto_accepted" if accepted else "needs_review",
        score,
        {},
        "synthetic-benchmark-v1",
    )


def _normalize_synthetic_mathjson(value: object) -> dict[str, object]:
    if isinstance(value, bool):
        raise ValueError("boolean MathJSON is unsupported")
    if isinstance(value, int | float):
        return {"type": "number", "value": str(value)}
    if isinstance(value, str):
        return {"type": "symbol", "name": value}
    if not isinstance(value, list) or not value or not isinstance(value[0], str):
        raise ValueError("synthetic MathJSON is invalid")
    operation = value[0]
    arguments = value[1:]
    if operation == "Add" and len(arguments) >= 2:
        return {
            "type": "add",
            "args": [_normalize_synthetic_mathjson(argument) for argument in arguments],
        }
    if operation == "Multiply" and len(arguments) >= 2:
        return {
            "type": "mul",
            "args": [_normalize_synthetic_mathjson(argument) for argument in arguments],
        }
    if operation == "Negate" and len(arguments) == 1:
        return {"type": "neg", "arg": _normalize_synthetic_mathjson(arguments[0])}
    if operation == "Divide" and len(arguments) == 2:
        return {
            "type": "div",
            "numerator": _normalize_synthetic_mathjson(arguments[0]),
            "denominator": _normalize_synthetic_mathjson(arguments[1]),
        }
    if operation == "Power" and len(arguments) == 2:
        return {
            "type": "pow",
            "base": _normalize_synthetic_mathjson(arguments[0]),
            "exponent": _normalize_synthetic_mathjson(arguments[1]),
        }
    raise ValueError("synthetic MathJSON operation is unsupported")


def _milliseconds(nanoseconds: int | float) -> float:
    return round(float(nanoseconds) / 1_000_000, 6)


def _matrix_digest(cases: Iterable[BenchmarkCase]) -> str:
    matrix = [
        {
            "case_id": case.case_id,
            "question_type": case.question_type,
            "load_bucket": case.load_bucket,
            "policy_version": case.policy_version,
            "expected_status": case.expected_status,
            "candidate_bytes": case.candidate_bytes,
        }
        for case in sorted(cases, key=lambda item: item.case_id)
    ]
    encoded = json.dumps(matrix, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _source_revision() -> str:
    return (
        os.environ.get("GITHUB_SHA")
        or os.environ.get("VERIFICATION_PERFORMANCE_SOURCE_REVISION")
        or "local"
    )


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.casefold().startswith("model name") and ":" in line:
                value = line.split(":", maxsplit=1)[1].strip()
                return value[:160] or "unknown"
    except OSError:
        pass
    return (platform.processor() or "unknown")[:160]


def _positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _non_negative_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value cannot be negative")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/verification-performance"),
    )
    parser.add_argument(
        "--warmups",
        type=_non_negative_integer,
        default=DEFAULT_WARMUP_RUNS,
    )
    parser.add_argument(
        "--iterations",
        type=_positive_integer,
        default=DEFAULT_MEASURED_RUNS,
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    arguments = parser.parse_args(argv)
    report = generate_production_report(
        warmup_runs=arguments.warmups,
        measured_runs=arguments.iterations,
        seed=arguments.seed,
    )
    paths = write_report(report, arguments.output_dir)
    print(paths.json_path)
    print(paths.markdown_path)
    summary = report["summary"]
    return 0 if isinstance(summary, dict) and summary.get("all_cases_succeeded") is True else 1


if __name__ == "__main__":
    sys.exit(main())
