"""Offline, de-identified release-gate evaluation for generated questions."""

from __future__ import annotations

from collections import Counter
from math import isfinite
from pathlib import Path
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

    @field_validator("model_id")
    @classmethod
    def _require_immutable_model_id(cls, model_id: str) -> str:
        return validate_immutable_openai_model_id(model_id)

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


class EvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    promotion_eligible: bool
    metrics: dict[str, EvaluationMetric]
    violations: list[EvaluationViolation]
    rejection_reason_counts: dict[str, int]
    cost_per_final_accepted_question: float | None
    end_to_end_duration_ms: dict[str, float | int]


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
    metric_definitions = (
        (
            "schema_pass_rate",
            sum(record.schema_valid for record in records),
            len(records),
            policy.thresholds.schema_pass_rate_min,
            "min",
            "evaluation_schema_pass_rate_below_threshold",
        ),
        (
            "math_answer_error_rate",
            sum(record.math_answer_correct is False for record in records),
            sum(record.math_answer_correct is not None for record in records),
            policy.thresholds.math_answer_error_rate_max,
            "max",
            "evaluation_math_answer_error_rate_above_threshold",
        ),
        (
            "grade_mismatch_rate",
            sum(not record.grade_aligned for record in records),
            len(records),
            policy.thresholds.grade_mismatch_rate_max,
            "max",
            "evaluation_grade_mismatch_rate_above_threshold",
        ),
        (
            "duplicate_or_similarity_rate",
            sum(record.duplicate_exact or record.similarity_high for record in records),
            len(records),
            policy.thresholds.duplicate_or_similarity_rate_max,
            "max",
            "evaluation_similarity_rate_above_threshold",
        ),
        (
            "teacher_direct_accept_rate",
            sum(record.teacher_outcome == "accepted_directly" for record in records),
            sum(record.teacher_outcome != "pending_review" for record in records),
            policy.thresholds.teacher_direct_accept_rate_min,
            "min",
            "evaluation_teacher_direct_accept_rate_below_threshold",
        ),
        (
            "teacher_modified_accept_rate",
            sum(record.teacher_outcome == "accepted_after_edit" for record in records),
            sum(record.teacher_edited for record in records),
            policy.thresholds.teacher_modified_accept_rate_min,
            "min",
            "evaluation_teacher_modified_accept_rate_below_threshold",
        ),
        (
            "published_without_teacher_review",
            sum(record.published and not record.review_evidence for record in records),
            len(records),
            policy.thresholds.published_without_teacher_review_max,
            "max",
            "evaluation_published_without_teacher_review",
        ),
    )
    metrics: dict[str, EvaluationMetric] = {}
    violations: list[EvaluationViolation] = []
    for name, numerator, denominator, threshold, comparator, code in metric_definitions:
        metric = _evaluate_metric(numerator, denominator, threshold, comparator)
        metrics[name] = metric
        if metric.state == "fail":
            violations.append(EvaluationViolation(code=code, metric=name))

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
    )


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
