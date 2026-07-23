"""Release-gate wrapper for offline, de-identified AI question evaluation."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from . import ai_evaluation


QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"]
_REQUIRED_TYPES: tuple[QuestionType, ...] = ("M1", "M2", "E1", "E2", "E3", "E4")


class EvidenceRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_question_types: tuple[QuestionType, ...] = _REQUIRED_TYPES
    minimum_total_records: int = Field(ge=1)
    minimum_records_per_question_type: int = Field(ge=1)
    minimum_reviewed_records_per_question_type: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_required_types(self) -> "EvidenceRequirements":
        if len(set(self.required_question_types)) != len(self.required_question_types):
            raise ValueError("required question types must be unique")
        if set(self.required_question_types) != set(_REQUIRED_TYPES):
            raise ValueError("the release gate must require M1, M2, E1, E2, E3, and E4")
        return self


class GatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str = Field(min_length=1, max_length=200)
    approved_model_ids: list[str] = Field(min_length=1)
    approved_prompt_versions: list[str] = Field(min_length=1)
    thresholds: ai_evaluation.EvaluationThresholds
    evidence_requirements: EvidenceRequirements

    def base_policy(self) -> ai_evaluation.EvaluationPolicy:
        return ai_evaluation.EvaluationPolicy(
            policy_id=self.policy_id,
            approved_model_ids=self.approved_model_ids,
            approved_prompt_versions=self.approved_prompt_versions,
            thresholds=self.thresholds,
        )


def load_policy(path: Path) -> GatePolicy:
    try:
        return GatePolicy.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ValueError(f"invalid evaluation policy: {path.name}") from error


def evaluate_records(
    records: Sequence[ai_evaluation.EvaluationRecord], policy: GatePolicy
) -> ai_evaluation.EvaluationReport:
    state_violations = _record_state_violations(records)
    valid_records = [record for record in records if not _record_state_reasons(record)]
    report = ai_evaluation.evaluate_records(valid_records, policy.base_policy())
    violations = [
        *report.violations,
        *_evidence_violations(valid_records, policy.evidence_requirements),
        *state_violations,
    ]
    violations = _deduplicate_violations(violations)
    return report.model_copy(
        update={
            "promotion_eligible": not violations,
            "violations": violations,
        }
    )


def _evidence_violations(
    records: Sequence[ai_evaluation.EvaluationRecord], requirements: EvidenceRequirements
) -> list[ai_evaluation.EvaluationViolation]:
    violations: list[ai_evaluation.EvaluationViolation] = []
    if len(records) < requirements.minimum_total_records:
        violations.append(
            _violation(
                "evaluation_insufficient_evidence",
                "sample_size",
                scope="global",
                observed=len(records),
                required=requirements.minimum_total_records,
            )
        )

    type_counts = Counter(record.question_type for record in records)
    reviewed_counts = Counter(
        record.question_type for record in records if record.teacher_outcome != "pending_review"
    )
    for question_type in requirements.required_question_types:
        observed = type_counts[question_type]
        if observed < requirements.minimum_records_per_question_type:
            violations.append(
                _violation(
                    "evaluation_insufficient_evidence",
                    "sample_size",
                    scope="question_type",
                    question_type=question_type,
                    observed=observed,
                    required=requirements.minimum_records_per_question_type,
                )
            )
        reviewed = reviewed_counts[question_type]
        if reviewed < requirements.minimum_reviewed_records_per_question_type:
            violations.append(
                _violation(
                    "evaluation_insufficient_review_evidence",
                    "review_sample_size",
                    scope="question_type",
                    question_type=question_type,
                    observed=reviewed,
                    required=requirements.minimum_reviewed_records_per_question_type,
                )
            )
    return violations


def _record_state_violations(
    records: Sequence[ai_evaluation.EvaluationRecord],
) -> list[ai_evaluation.EvaluationViolation]:
    violations: list[ai_evaluation.EvaluationViolation] = []
    for record in records:
        for reason in _record_state_reasons(record):
            violations.append(
                _violation(
                    "evaluation_record_state_invalid",
                    "record_state",
                    record_id=record.record_id,
                    reason=reason,
                )
            )
    return violations


def _record_state_reasons(record: ai_evaluation.EvaluationRecord) -> list[str]:
    reasons: list[str] = []
    is_math = record.question_type in {"M1", "M2"}
    if is_math and record.math_answer_correct is None:
        reasons.append("math_answer_result_missing")
    if not is_math and record.math_answer_correct is not None:
        reasons.append("english_record_has_math_answer_result")

    if record.teacher_outcome == "accepted_directly" and record.teacher_edited:
        reasons.append("direct_accept_marked_edited")
    if record.teacher_outcome == "accepted_after_edit" and not record.teacher_edited:
        reasons.append("edited_accept_missing_edit")

    if record.teacher_outcome == "rejected":
        if record.rejection_category is None:
            reasons.append("rejection_category_missing")
        if record.published:
            reasons.append("rejected_record_published")
        if not record.review_evidence:
            reasons.append("rejected_record_missing_review_evidence")
    elif record.rejection_category is not None:
        reasons.append("rejection_category_on_non_rejected_record")

    if record.teacher_outcome == "pending_review":
        if record.published:
            reasons.append("pending_record_published")
        if record.review_evidence:
            reasons.append("pending_record_claims_review_evidence")
    elif not record.review_evidence:
        reasons.append("completed_review_missing_evidence")

    if record.published and record.teacher_outcome not in {
        "accepted_directly",
        "accepted_after_edit",
    }:
        reasons.append("publication_without_acceptance")
    return reasons


def _violation(code: str, metric: str, **key: str | int) -> ai_evaluation.EvaluationViolation:
    return ai_evaluation.EvaluationViolation(
        code=code,
        metric=metric,
        key={name: str(value) for name, value in key.items()},
    )


def _deduplicate_violations(
    violations: Sequence[ai_evaluation.EvaluationViolation],
) -> list[ai_evaluation.EvaluationViolation]:
    unique: dict[str, ai_evaluation.EvaluationViolation] = {}
    for violation in violations:
        identity = json.dumps(violation.model_dump(mode="json"), sort_keys=True)
        unique.setdefault(identity, violation)
    return list(unique.values())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate AI question generation quality")
    parser.add_argument("policy_path", type=Path)
    parser.add_argument("records_path", type=Path)
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args(argv)

    policy = load_policy(arguments.policy_path)
    records = ai_evaluation.load_records(arguments.records_path)
    report = evaluate_records(records, policy)
    ai_evaluation.write_report(report, arguments.output_directory)
    return 0 if report.promotion_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
