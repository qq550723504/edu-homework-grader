"""Offline, de-identified release-gate evaluation for generated questions."""

from __future__ import annotations

import argparse
from collections import Counter
from html import escape
import json
from math import isfinite
from pathlib import Path
import sys
from typing import Literal, Sequence

from edu_generator.model_snapshots import validate_immutable_openai_model_id
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"]
TeacherOutcome = Literal["accepted_directly", "accepted_after_edit", "rejected", "pending_review"]
MetricComparator = Literal["min", "max"]


class EvaluationThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_pass_rate_min: float = Field(ge=0, le=1)
    math_answer_error_rate_max: float = Field(ge=0, le=1)
    grade_mismatch_rate_max: float = Field(ge=0, le=1)
    duplicate_or_similarity_rate_max: float = Field(ge=0, le=1)
    teacher_direct_accept_rate_min: float = Field(ge=0, le=1)
    teacher_modified_accept_rate_min: float = Field(ge=0, le=1)
    published_without_teacher_review_max: int = Field(ge=0)


class EvaluationPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=200)
    approved_model_ids: list[str] = Field(min_length=1)
    approved_prompt_versions: list[str] = Field(min_length=1)
    thresholds: EvaluationThresholds


class EvaluationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, max_length=200)
    run_id: str = Field(min_length=1, max_length=200)
    curriculum_profile: str = Field(min_length=1, max_length=200)
    grade: str = Field(min_length=1, max_length=50)
    subject: str = Field(min_length=1, max_length=100)
    question_type: QuestionType
    model_id: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=200)
    validator_version: str = Field(min_length=1, max_length=200)
    difficulty_band: str = Field(min_length=1, max_length=100)
    seed: int
    parameters: dict[str, object]
    content_fingerprint: str = Field(min_length=1, max_length=200)
    schema_valid: bool
    math_answer_correct: bool | None
    grade_aligned: bool
    duplicate_exact: bool
    similarity_high: bool
    teacher_outcome: TeacherOutcome
    teacher_edited: bool
    rejection_category: str | None = Field(default=None, max_length=100)
    published: bool
    review_evidence: bool
    cost_usd: float = Field(ge=0)
    duration_ms: int = Field(ge=0)

    @field_validator("cost_usd")
    @classmethod
    def _require_finite_cost(cls, cost_usd: float) -> float:
        if not isfinite(cost_usd):
            raise ValueError("cost_usd must be finite")
        return cost_usd


class EvaluationMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    rate: float | None = Field(default=None, ge=0, le=1)
    threshold: float | int
    comparator: MetricComparator
    state: Literal["pass", "fail", "not_applicable"]


class EvaluationViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=200)
    metric: str = Field(min_length=1, max_length=200)
    key: dict[str, str] = Field(default_factory=dict)


class EvaluationScopeSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: dict[str, str]
    metrics: dict[str, EvaluationMetric]
    metric_deltas: dict[str, float | None] = Field(default_factory=dict)


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    promotion_eligible: bool
    metrics: dict[str, EvaluationMetric]
    violations: list[EvaluationViolation]
    rejection_reason_counts: dict[str, int]
    cost_per_final_accepted_question: float | None
    end_to_end_duration_ms: dict[str, float | int]
    strata: list[EvaluationScopeSummary] = Field(default_factory=list)
    version_summaries: list[EvaluationScopeSummary] = Field(default_factory=list)


def load_policy(path: Path) -> EvaluationPolicy:
    try:
        return EvaluationPolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ValueError(f"invalid evaluation policy: {path.name}") from error


def load_records(path: Path) -> list[EvaluationRecord]:
    records: list[EvaluationRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"unable to read evaluation records: {path.name}") from error

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(EvaluationRecord.model_validate_json(line))
        except ValidationError as error:
            locations = ", ".join(
                ".".join(str(part) for part in item["loc"]) for item in error.errors()
            )
            raise ValueError(f"invalid evaluation record at line {number}: {locations}") from error
    return records


def evaluate_records(
    records: Sequence[EvaluationRecord], policy: EvaluationPolicy
) -> EvaluationReport:
    metric_definitions = _metric_definitions(records, policy.thresholds)
    metrics, violations = _evaluate_metric_definitions(metric_definitions)
    violations.extend(_version_approval_violations(records, policy))
    violations.extend(_duplicate_record_id_violations(records))

    strata = _scope_summaries(
        records,
        policy.thresholds,
        (
            "curriculum_profile",
            "grade",
            "subject",
            "question_type",
            "model_id",
            "prompt_version",
            "validator_version",
            "difficulty_band",
        ),
    )
    version_summaries = _scope_summaries(
        records,
        policy.thresholds,
        ("model_id", "prompt_version", "validator_version"),
    )
    for summary in [*strata, *version_summaries]:
        _, summary_violations = _evaluate_metric_definitions(summary.metrics.items())
        for violation in summary_violations:
            violations.append(violation.model_copy(update={"key": summary.key}))
    _add_version_metric_deltas(version_summaries)

    final_accepts = [
        record
        for record in records
        if record.teacher_outcome in {"accepted_directly", "accepted_after_edit"}
    ]
    rejections = Counter(
        record.rejection_category
        for record in records
        if record.teacher_outcome == "rejected" and record.rejection_category is not None
    )
    durations = [record.duration_ms for record in records]
    return EvaluationReport(
        policy_id=policy.policy_id,
        promotion_eligible=not violations,
        metrics=metrics,
        violations=violations,
        rejection_reason_counts=dict(sorted(rejections.items())),
        cost_per_final_accepted_question=(
            sum(record.cost_usd for record in records) / len(final_accepts)
            if final_accepts
            else None
        ),
        end_to_end_duration_ms={
            "average": sum(durations) / len(durations) if durations else 0.0,
            "maximum": max(durations, default=0),
        },
        strata=strata,
        version_summaries=version_summaries,
    )


def _metric_definitions(
    records: Sequence[EvaluationRecord], thresholds: EvaluationThresholds
) -> tuple[tuple[str, int, int, float | int, MetricComparator, str], ...]:
    return (
        (
            "schema_pass_rate",
            sum(record.schema_valid for record in records),
            len(records),
            thresholds.schema_pass_rate_min,
            "min",
            "evaluation_schema_pass_rate_below_threshold",
        ),
        (
            "math_answer_error_rate",
            sum(record.math_answer_correct is False for record in records),
            sum(record.math_answer_correct is not None for record in records),
            thresholds.math_answer_error_rate_max,
            "max",
            "evaluation_math_answer_error_rate_above_threshold",
        ),
        (
            "grade_mismatch_rate",
            sum(not record.grade_aligned for record in records),
            len(records),
            thresholds.grade_mismatch_rate_max,
            "max",
            "evaluation_grade_mismatch_rate_above_threshold",
        ),
        (
            "duplicate_or_similarity_rate",
            sum(record.duplicate_exact or record.similarity_high for record in records),
            len(records),
            thresholds.duplicate_or_similarity_rate_max,
            "max",
            "evaluation_similarity_rate_above_threshold",
        ),
        (
            "teacher_direct_accept_rate",
            sum(record.teacher_outcome == "accepted_directly" for record in records),
            sum(record.teacher_outcome != "pending_review" for record in records),
            thresholds.teacher_direct_accept_rate_min,
            "min",
            "evaluation_teacher_direct_accept_rate_below_threshold",
        ),
        (
            "teacher_modified_accept_rate",
            sum(record.teacher_outcome == "accepted_after_edit" for record in records),
            sum(record.teacher_edited for record in records),
            thresholds.teacher_modified_accept_rate_min,
            "min",
            "evaluation_teacher_modified_accept_rate_below_threshold",
        ),
        (
            "published_without_teacher_review",
            sum(record.published and not record.review_evidence for record in records),
            len(records),
            thresholds.published_without_teacher_review_max,
            "max",
            "evaluation_published_without_teacher_review",
        ),
    )


def _evaluate_metric_definitions(
    definitions: Sequence[
        tuple[str, int, int, float | int, MetricComparator, str] | tuple[str, EvaluationMetric]
    ],
) -> tuple[dict[str, EvaluationMetric], list[EvaluationViolation]]:
    metrics: dict[str, EvaluationMetric] = {}
    violations: list[EvaluationViolation] = []
    for definition in definitions:
        if len(definition) == 2:
            name, metric = definition
            code = _violation_code_for_metric(name)
        else:
            name, numerator, denominator, threshold, comparator, code = definition
            metric = _evaluate_metric(numerator, denominator, threshold, comparator)
        metrics[name] = metric
        if metric.state == "fail":
            violations.append(EvaluationViolation(code=code, metric=name))
    return metrics, violations


def _violation_code_for_metric(metric: str) -> str:
    return {
        "schema_pass_rate": "evaluation_schema_pass_rate_below_threshold",
        "math_answer_error_rate": "evaluation_math_answer_error_rate_above_threshold",
        "grade_mismatch_rate": "evaluation_grade_mismatch_rate_above_threshold",
        "duplicate_or_similarity_rate": "evaluation_similarity_rate_above_threshold",
        "teacher_direct_accept_rate": "evaluation_teacher_direct_accept_rate_below_threshold",
        "teacher_modified_accept_rate": "evaluation_teacher_modified_accept_rate_below_threshold",
        "published_without_teacher_review": "evaluation_published_without_teacher_review",
    }[metric]


def _version_approval_violations(
    records: Sequence[EvaluationRecord], policy: EvaluationPolicy
) -> list[EvaluationViolation]:
    violations: list[EvaluationViolation] = []
    for record in records:
        try:
            validate_immutable_openai_model_id(record.model_id)
        except ValueError:
            violations.append(
                EvaluationViolation(
                    code="evaluation_unapproved_model",
                    metric="model_approval",
                    key={"model_id": record.model_id},
                )
            )
            continue
        if record.model_id not in policy.approved_model_ids:
            violations.append(
                EvaluationViolation(
                    code="evaluation_unapproved_model",
                    metric="model_approval",
                    key={"model_id": record.model_id},
                )
            )
        if record.prompt_version not in policy.approved_prompt_versions:
            violations.append(
                EvaluationViolation(
                    code="evaluation_unapproved_prompt",
                    metric="prompt_approval",
                    key={"prompt_version": record.prompt_version},
                )
            )
    return violations


def _duplicate_record_id_violations(
    records: Sequence[EvaluationRecord],
) -> list[EvaluationViolation]:
    record_ids = Counter(record.record_id for record in records)
    return [
        EvaluationViolation(
            code="evaluation_duplicate_record_id",
            metric="record_identity",
            key={"record_id": record_id},
        )
        for record_id, count in sorted(record_ids.items())
        if count > 1
    ]


def _scope_summaries(
    records: Sequence[EvaluationRecord],
    thresholds: EvaluationThresholds,
    fields: tuple[str, ...],
) -> list[EvaluationScopeSummary]:
    grouped: dict[tuple[str, ...], list[EvaluationRecord]] = {}
    for record in records:
        values = tuple(str(getattr(record, field)) for field in fields)
        grouped.setdefault(values, []).append(record)
    return [
        EvaluationScopeSummary(
            key=dict(zip(fields, values, strict=True)),
            metrics=_evaluate_metric_definitions(_metric_definitions(group, thresholds))[0],
        )
        for values, group in sorted(grouped.items())
    ]


def _add_version_metric_deltas(summaries: list[EvaluationScopeSummary]) -> None:
    if not summaries:
        return
    baseline = summaries[0].metrics
    for summary in summaries:
        summary.metric_deltas = {
            name: (
                None
                if metric.rate is None or baseline[name].rate is None
                else metric.rate - baseline[name].rate
            )
            for name, metric in summary.metrics.items()
        }


def write_report(report: EvaluationReport, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    json_path = output_dir / "report.json"
    html_path = output_dir / "report.html"
    rendered_json = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    json_path.write_text(f"{rendered_json}\n", encoding="utf-8")
    html_path.write_text(_render_html_report(rendered_json), encoding="utf-8")
    return json_path, html_path


def _render_html_report(rendered_json: str) -> str:
    return "\n".join(
        (
            "<!doctype html>",
            '<html lang="en">',
            '<head><meta charset="utf-8"><title>AI evaluation report</title></head>',
            "<body><h1>AI evaluation report</h1>",
            f"<pre>{escape(rendered_json)}</pre>",
            "</body></html>",
            "",
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate AI question generation quality")
    parser.add_argument("policy_path", type=Path)
    parser.add_argument("records_path", type=Path)
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args(argv)
    report = evaluate_records(
        load_records(arguments.records_path), load_policy(arguments.policy_path)
    )
    write_report(report, arguments.output_directory)
    return 0 if report.promotion_eligible else 1


def _evaluate_metric(
    numerator: int, denominator: int, threshold: float | int, comparator: MetricComparator
) -> EvaluationMetric:
    if denominator == 0:
        return EvaluationMetric(
            numerator=numerator,
            denominator=denominator,
            rate=None,
            threshold=threshold,
            comparator=comparator,
            state="not_applicable",
        )
    rate = numerator / denominator
    passes = rate >= threshold if comparator == "min" else rate <= threshold
    return EvaluationMetric(
        numerator=numerator,
        denominator=denominator,
        rate=rate,
        threshold=threshold,
        comparator=comparator,
        state="pass" if passes else "fail",
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
