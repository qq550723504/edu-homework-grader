"""Export de-identified AI-authoring facts and compare explicit versions."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys
from typing import Literal, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GeneratedQuestionReviewDecision,
    GenerationControlState,
    GenerationGovernanceTargetType,
    GenerationJob,
    GenerationValidationRun,
)
from . import ai_evaluation, ai_evaluation_gate
from .generation import GenerationServiceError, generation_plan_item_for_ordinal
from .generation_governance import controls_for_target

EXPORTER_VERSION = "operational-ai-evaluation-export-v1"
_METRICS = (
    "schema_pass_rate",
    "math_answer_error_rate",
    "grade_mismatch_rate",
    "duplicate_or_similarity_rate",
    "teacher_direct_accept_rate",
    "teacher_modified_accept_rate",
    "published_without_teacher_review",
)
_STRATUM_FIELDS = (
    "curriculum_profile",
    "grade",
    "subject",
    "question_type",
    "difficulty_band",
)
_SCHEMA_CODES = frozenset(
    {"policy_schema_invalid", "prompt_or_explanation_invalid", "unsupported_consistency_structure"}
)
_MATH_CODES = frozenset(
    {
        "m1_answer_invalid",
        "m1_grader_probe_failed",
        "m2_mathjson_invalid",
        "m2_grader_probe_failed",
        "answer_explanation_inconsistent",
        "score_total_inconsistent",
        "unsupported_consistency_structure",
    }
)
_GRADE_CODES = frozenset(
    {
        "curriculum_revision_inactive",
        "curriculum_objective_mismatch",
        "difficulty_out_of_range",
        "question_type_not_allowed",
        "grade_complexity_rules_invalid",
        "grade_complexity_warning",
    }
)
_UNAVAILABLE_CODES = frozenset({"validator_unavailable", "duplicate_semantic_check_unavailable"})
_EXACT_DUPLICATE_CODES = frozenset({"duplicate_exact_prompt"})
_SIMILARITY_CODES = frozenset({"duplicate_normalized_prompt", "duplicate_semantic_near_match"})


class EvaluationExportSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    run_id: str = Field(min_length=1, max_length=200)
    watermark: datetime

    @model_validator(mode="after")
    def require_timezone(self) -> "EvaluationExportSpec":
        if self.watermark.tzinfo is None or self.watermark.utcoffset() is None:
            raise ValueError("watermark must include an explicit timezone")
        return self


class EvaluationVersionSelector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=200)
    prompt_version: str = Field(min_length=1, max_length=200)
    validator_version: str = Field(min_length=1, max_length=200)


class OperationalEvaluationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str = Field(min_length=1, max_length=200)
    export: EvaluationExportSpec
    baseline: EvaluationVersionSelector
    candidate: EvaluationVersionSelector
    gate_policy: ai_evaluation_gate.GatePolicy
    max_metric_regression: dict[str, float] = Field(default_factory=dict)
    stratum_fields: tuple[str, ...] = _STRATUM_FIELDS

    @model_validator(mode="after")
    def validate_versions(self) -> "OperationalEvaluationSpec":
        if self.baseline == self.candidate:
            raise ValueError("baseline and candidate versions must be different")
        if not self.stratum_fields or len(set(self.stratum_fields)) != len(self.stratum_fields):
            raise ValueError("stratum_fields must be non-empty and unique")
        if not set(self.stratum_fields).issubset(_STRATUM_FIELDS):
            raise ValueError("stratum_fields contains an unsupported field")
        if set(self.max_metric_regression) - set(_METRICS):
            raise ValueError("max_metric_regression contains an unsupported metric")
        if any(value < 0 for value in self.max_metric_regression.values()):
            raise ValueError("max_metric_regression values must be non-negative")
        approved_models = set(self.gate_policy.approved_model_ids)
        approved_prompts = set(self.gate_policy.approved_prompt_versions)
        if {self.baseline.model_id, self.candidate.model_id} - approved_models:
            raise ValueError("comparison model IDs must be approved by the gate policy")
        if {self.baseline.prompt_version, self.candidate.prompt_version} - approved_prompts:
            raise ValueError("comparison Prompt versions must be approved by the gate policy")
        return self


class EvaluationExportIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    draft_id: str
    detail: dict[str, str] = Field(default_factory=dict)


class EvaluationExportManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exporter_version: str
    run_id: str
    tenant_id: str
    watermark: datetime
    record_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    record_digest: str = Field(min_length=64, max_length=64)
    source_counts: dict[str, int]


class EvaluationExportResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    records: list[ai_evaluation.EvaluationRecord]
    issues: list[EvaluationExportIssue]
    manifest: EvaluationExportManifest


class VersionMetricComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: ai_evaluation.EvaluationMetric
    candidate: ai_evaluation.EvaluationMetric
    regression: float | None
    allowed_regression: float = Field(ge=0)
    state: Literal["pass", "fail", "not_applicable"]


class OperationalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec_id: str
    exporter_version: str
    run_id: str
    tenant_id: str
    watermark: datetime
    baseline: EvaluationVersionSelector
    candidate: EvaluationVersionSelector
    promotion_eligible: bool
    export_manifest: EvaluationExportManifest
    baseline_gate: ai_evaluation.EvaluationReport | None = None
    candidate_gate: ai_evaluation.EvaluationReport | None = None
    metric_comparisons: dict[str, VersionMetricComparison] = Field(default_factory=dict)
    strata: list[dict[str, object]] = Field(default_factory=list)
    violations: list[ai_evaluation.EvaluationViolation] = Field(default_factory=list)


def load_operational_spec(path: Path) -> OperationalEvaluationSpec:
    try:
        return OperationalEvaluationSpec.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as error:
        raise ValueError(f"invalid operational evaluation spec: {path.name}") from error


def export_evaluation_records(
    session: Session, spec: EvaluationExportSpec
) -> EvaluationExportResult:
    drafts = list(
        session.scalars(
            select(GeneratedQuestionDraft)
            .join(GenerationJob, GeneratedQuestionDraft.job_id == GenerationJob.id)
            .where(
                GenerationJob.tenant_id == spec.tenant_id,
                GeneratedQuestionDraft.created_at <= spec.watermark,
            )
            .order_by(GeneratedQuestionDraft.created_at, GeneratedQuestionDraft.id)
        )
    )
    attempt_counts = Counter(draft.generation_attempt_id for draft in drafts)
    records: list[ai_evaluation.EvaluationRecord] = []
    issues: list[EvaluationExportIssue] = []
    outcomes: Counter[str] = Counter()
    for draft in drafts:
        record, record_issues = _record_for_draft(
            session,
            draft=draft,
            spec=spec,
            attempt_count=attempt_counts[draft.generation_attempt_id],
        )
        issues.extend(record_issues)
        if record is not None:
            records.append(record)
            outcomes[record.teacher_outcome] += 1
    records.sort(key=lambda record: record.record_id)
    serialized = _serialize_records(records)
    return EvaluationExportResult(
        records=records,
        issues=issues,
        manifest=EvaluationExportManifest(
            exporter_version=EXPORTER_VERSION,
            run_id=spec.run_id,
            tenant_id=str(spec.tenant_id),
            watermark=spec.watermark,
            record_count=len(records),
            issue_count=len(issues),
            record_digest=sha256(serialized.encode()).hexdigest(),
            source_counts=dict(sorted(outcomes.items())),
        ),
    )


def _record_for_draft(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    spec: EvaluationExportSpec,
    attempt_count: int,
) -> tuple[ai_evaluation.EvaluationRecord | None, list[EvaluationExportIssue]]:
    evidence = _select_evidence(session, draft=draft, watermark=spec.watermark)
    if evidence is None:
        return None, [_issue("evaluation_export_evidence_missing", draft)]
    revision, validation_run, decision = evidence
    issues: list[EvaluationExportIssue] = []
    if validation_run.draft_revision_id != revision.id:
        issues.append(_issue("evaluation_export_validation_revision_mismatch", draft))
    if validation_run.generated_question_draft_id != draft.id:
        issues.append(_issue("evaluation_export_validation_draft_mismatch", draft))
    if decision is not None and decision.generation_validation_run_id != validation_run.id:
        issues.append(_issue("evaluation_export_decision_validation_mismatch", draft))
    codes = {finding.code for finding in validation_run.findings}
    unavailable = sorted(codes & _UNAVAILABLE_CODES)
    if unavailable:
        issues.append(
            _issue(
                "evaluation_export_validation_unavailable",
                draft,
                finding_codes=",".join(unavailable),
            )
        )
    difficulty = validation_run.feature_summary_json.get("difficulty_signal")
    if not isinstance(difficulty, dict) or difficulty.get("availability") != "available":
        issues.append(_issue("evaluation_export_difficulty_signal_missing", draft))
    if issues:
        return None, issues

    candidate = revision.candidate_json
    question_type = candidate.get("question_type") if isinstance(candidate, dict) else None
    if question_type not in {"M1", "M2", "E1", "E2", "E3", "E4"}:
        return None, [_issue("evaluation_export_question_type_invalid", draft)]
    job = draft.job
    attempt = draft.generation_attempt
    try:
        plan = generation_plan_item_for_ordinal(job, draft.ordinal)
    except GenerationServiceError:
        return None, [_issue("evaluation_export_plan_invalid", draft)]
    if plan.question_type != question_type:
        return None, [_issue("evaluation_export_plan_question_type_mismatch", draft)]

    outcome = _review_fields(decision, revision, spec.watermark)
    if outcome is None:
        return None, [_issue("evaluation_export_review_action_invalid", draft)]
    teacher_outcome, teacher_edited, rejection, published, reviewed = outcome
    objective = job.curriculum_objective_revision.objective
    profile = job.curriculum_profile or objective.profile
    request_summary = attempt.request_summary if isinstance(attempt.request_summary, dict) else {}
    template = request_summary.get("prompt_template")
    fingerprint = template.get("fingerprint") if isinstance(template, dict) else None
    divisor = max(attempt_count, 1)
    parameters: dict[str, object] = {
        "provider_name": attempt.provider_name,
        "attempt_number": attempt.attempt_number,
        "policy_catalog_version": job.policy_version or "unknown",
        "ruleset_version": validation_run.ruleset_version,
        "objective_revision_id": str(job.curriculum_objective_revision_id),
        "prompt_template_fingerprint": fingerprint or "unknown",
        "cost_observed": attempt.cost_usd is not None,
        "seed_observed": attempt.seed is not None,
    }
    return (
        ai_evaluation.EvaluationRecord(
            record_id=f"{draft.id}:{revision.id}",
            run_id=spec.run_id,
            curriculum_profile=profile.code,
            grade=job.grade or objective.grade_mapping.internal_level,
            subject=job.subject or objective.subject,
            question_type=question_type,
            model_id=attempt.model_version,
            prompt_version=attempt.prompt_version,
            validator_version=validation_run.validator_version,
            difficulty_band=plan.difficulty_band,
            seed=attempt.seed if attempt.seed is not None else 0,
            parameters=parameters,
            content_fingerprint=revision.content_hash,
            schema_valid=not bool(codes & _SCHEMA_CODES),
            math_answer_correct=(
                not bool(codes & _MATH_CODES) if question_type in {"M1", "M2"} else None
            ),
            grade_aligned=not bool(codes & _GRADE_CODES),
            duplicate_exact=bool(codes & _EXACT_DUPLICATE_CODES),
            similarity_high=bool(codes & _SIMILARITY_CODES),
            teacher_outcome=teacher_outcome,
            teacher_edited=teacher_edited,
            rejection_category=rejection,
            published=published,
            review_evidence=reviewed,
            cost_usd=max(float(attempt.cost_usd or 0), 0) / divisor,
            duration_ms=round(max(int(attempt.duration_ms or 0), 0) / divisor),
        ),
        [],
    )


def _select_evidence(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    watermark: datetime,
) -> (
    tuple[
        GeneratedQuestionDraftRevision,
        GenerationValidationRun,
        GeneratedQuestionReviewDecision | None,
    ]
    | None
):
    decision = session.scalar(
        select(GeneratedQuestionReviewDecision)
        .where(
            GeneratedQuestionReviewDecision.generated_question_draft_id == draft.id,
            GeneratedQuestionReviewDecision.created_at <= watermark,
        )
        .order_by(
            GeneratedQuestionReviewDecision.created_at.desc(),
            GeneratedQuestionReviewDecision.id.desc(),
        )
        .limit(1)
    )
    if decision is not None:
        revision = session.get(GeneratedQuestionDraftRevision, decision.draft_revision_id)
        run = session.get(GenerationValidationRun, decision.generation_validation_run_id)
        return (revision, run, decision) if revision is not None and run is not None else None
    revision = session.scalar(
        select(GeneratedQuestionDraftRevision)
        .where(
            GeneratedQuestionDraftRevision.generated_question_draft_id == draft.id,
            GeneratedQuestionDraftRevision.created_at <= watermark,
        )
        .order_by(
            GeneratedQuestionDraftRevision.revision_number.desc(),
            GeneratedQuestionDraftRevision.id.desc(),
        )
        .limit(1)
    )
    if revision is None:
        return None
    run = session.scalar(
        select(GenerationValidationRun)
        .where(
            GenerationValidationRun.generated_question_draft_id == draft.id,
            GenerationValidationRun.draft_revision_id == revision.id,
            GenerationValidationRun.created_at <= watermark,
        )
        .order_by(GenerationValidationRun.run_number.desc(), GenerationValidationRun.id.desc())
        .limit(1)
    )
    return (revision, run, None) if run is not None else None


def _review_fields(
    decision: GeneratedQuestionReviewDecision | None,
    revision: GeneratedQuestionDraftRevision,
    watermark: datetime,
) -> tuple[ai_evaluation.TeacherOutcome, bool, str | None, bool, bool] | None:
    if decision is None:
        return "pending_review", False, None, False, False
    edited = revision.editor_user_id is not None or revision.revision_number > 1
    if decision.action == "accept":
        version = decision.accepted_question_version
        published = bool(
            version is not None
            and version.published_at is not None
            and _at_or_before(version.published_at, watermark)
        )
        return (
            "accepted_after_edit" if edited else "accepted_directly",
            edited,
            None,
            published,
            version is not None,
        )
    if decision.action == "reject":
        category = (decision.reason or "other").partition(":")[0].strip() or "other"
        return "rejected", edited, category, False, True
    return None


def _at_or_before(value: datetime, watermark: datetime) -> bool:
    value = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    watermark = (
        watermark if watermark.tzinfo is not None else watermark.replace(tzinfo=timezone.utc)
    )
    return value <= watermark


def compare_evaluation_records(
    session: Session,
    *,
    records: Sequence[ai_evaluation.EvaluationRecord],
    spec: OperationalEvaluationSpec,
    manifest: EvaluationExportManifest,
) -> OperationalEvaluationReport:
    baseline = [record for record in records if _matches(record, spec.baseline)]
    candidate = [record for record in records if _matches(record, spec.candidate)]
    baseline_gate = ai_evaluation_gate.evaluate_records(baseline, spec.gate_policy)
    candidate_gate = ai_evaluation_gate.evaluate_records(candidate, spec.gate_policy)
    violations = [
        *_governance_violations(session, spec),
        *_prefix_gate("baseline", baseline_gate.violations),
        *_prefix_gate("candidate", candidate_gate.violations),
    ]
    metrics, metric_violations = _compare_metrics(
        baseline_gate.metrics, candidate_gate.metrics, spec.max_metric_regression
    )
    strata, stratum_violations = _compare_strata(baseline, candidate, spec)
    violations = _deduplicate([*violations, *metric_violations, *stratum_violations])
    return OperationalEvaluationReport(
        spec_id=spec.spec_id,
        exporter_version=EXPORTER_VERSION,
        run_id=spec.export.run_id,
        tenant_id=str(spec.export.tenant_id),
        watermark=spec.export.watermark,
        baseline=spec.baseline,
        candidate=spec.candidate,
        promotion_eligible=not violations,
        export_manifest=manifest,
        baseline_gate=baseline_gate,
        candidate_gate=candidate_gate,
        metric_comparisons=metrics,
        strata=strata,
        violations=violations,
    )


def run_operational_evaluation(
    session: Session, spec: OperationalEvaluationSpec
) -> tuple[EvaluationExportResult, OperationalEvaluationReport]:
    exported = export_evaluation_records(session, spec.export)
    if exported.issues:
        violations = [
            ai_evaluation.EvaluationViolation(
                code=issue.code,
                metric="production_export",
                key={"draft_id": issue.draft_id, **issue.detail},
            )
            for issue in exported.issues
        ]
        report = OperationalEvaluationReport(
            spec_id=spec.spec_id,
            exporter_version=EXPORTER_VERSION,
            run_id=spec.export.run_id,
            tenant_id=str(spec.export.tenant_id),
            watermark=spec.export.watermark,
            baseline=spec.baseline,
            candidate=spec.candidate,
            promotion_eligible=False,
            export_manifest=exported.manifest,
            violations=violations,
        )
        return exported, report
    return exported, compare_evaluation_records(
        session, records=exported.records, spec=spec, manifest=exported.manifest
    )


def _matches(record: ai_evaluation.EvaluationRecord, selector: EvaluationVersionSelector) -> bool:
    return (
        record.model_id == selector.model_id
        and record.prompt_version == selector.prompt_version
        and record.validator_version == selector.validator_version
        and record.parameters.get("provider_name") == selector.provider_name
    )


def _governance_violations(
    session: Session, spec: OperationalEvaluationSpec
) -> list[ai_evaluation.EvaluationViolation]:
    violations: list[ai_evaluation.EvaluationViolation] = []
    for role, selector, allowed in (
        ("baseline", spec.baseline, {"active"}),
        ("candidate", spec.candidate, {"active", "canary"}),
    ):
        targets = (
            (GenerationGovernanceTargetType.PROVIDER, selector.provider_name),
            (GenerationGovernanceTargetType.MODEL, selector.model_id),
            (GenerationGovernanceTargetType.PROMPT_VERSION, selector.prompt_version),
        )
        for target_type, target_key in targets:
            effective = _effective_state(session, spec.export.tenant_id, target_type, target_key)
            if effective not in allowed:
                violations.append(
                    ai_evaluation.EvaluationViolation(
                        code="evaluation_governance_approval_missing",
                        metric="version_governance",
                        key={
                            "role": role,
                            "target_type": target_type.value,
                            "target_key": target_key,
                            "effective_state": effective,
                        },
                    )
                )
    return violations


def _effective_state(
    session: Session,
    tenant_id: UUID,
    target_type: GenerationGovernanceTargetType,
    target_key: str,
) -> str:
    tenant_state, global_state = controls_for_target(
        session,
        tenant_id=tenant_id,
        target_type=target_type,
        target_key=target_key,
    )
    blocked = {GenerationControlState.PAUSED, GenerationControlState.RETIRED}
    if global_state in blocked or tenant_state in blocked:
        return "blocked"
    if global_state is GenerationControlState.CANARY:
        return "canary" if tenant_state is GenerationControlState.CANARY else "blocked"
    if tenant_state is GenerationControlState.CANARY:
        return "canary"
    if GenerationControlState.ACTIVE in {tenant_state, global_state}:
        return "active"
    return "unspecified"


def _prefix_gate(
    role: str, violations: Sequence[ai_evaluation.EvaluationViolation]
) -> list[ai_evaluation.EvaluationViolation]:
    return [
        violation.model_copy(update={"key": {"version_role": role, **violation.key}})
        for violation in violations
    ]


def _compare_metrics(
    baseline: dict[str, ai_evaluation.EvaluationMetric],
    candidate: dict[str, ai_evaluation.EvaluationMetric],
    allowed_regressions: dict[str, float],
    *,
    key: dict[str, str] | None = None,
) -> tuple[dict[str, VersionMetricComparison], list[ai_evaluation.EvaluationViolation]]:
    comparisons: dict[str, VersionMetricComparison] = {}
    violations: list[ai_evaluation.EvaluationViolation] = []
    for name in _METRICS:
        baseline_metric = baseline[name]
        candidate_metric = candidate[name]
        allowed = allowed_regressions.get(name, 0.0)
        if baseline_metric.rate is None and candidate_metric.rate is None:
            regression = None
            state: Literal["pass", "fail", "not_applicable"] = "not_applicable"
        elif baseline_metric.rate is None or candidate_metric.rate is None:
            regression, state = None, "fail"
        else:
            regression = (
                baseline_metric.rate - candidate_metric.rate
                if baseline_metric.comparator == "min"
                else candidate_metric.rate - baseline_metric.rate
            )
            state = "fail" if regression > allowed else "pass"
        comparisons[name] = VersionMetricComparison(
            baseline=baseline_metric,
            candidate=candidate_metric,
            regression=regression,
            allowed_regression=allowed,
            state=state,
        )
        if state == "fail":
            violations.append(
                ai_evaluation.EvaluationViolation(
                    code="evaluation_candidate_regression",
                    metric=name,
                    key={**(key or {}), "allowed_regression": str(allowed)},
                )
            )
    return comparisons, violations


def _compare_strata(
    baseline: Sequence[ai_evaluation.EvaluationRecord],
    candidate: Sequence[ai_evaluation.EvaluationRecord],
    spec: OperationalEvaluationSpec,
) -> tuple[list[dict[str, object]], list[ai_evaluation.EvaluationViolation]]:
    baseline_groups = _groups(baseline, spec.stratum_fields)
    candidate_groups = _groups(candidate, spec.stratum_fields)
    summaries: list[dict[str, object]] = []
    violations: list[ai_evaluation.EvaluationViolation] = []
    for values in sorted(set(baseline_groups) | set(candidate_groups)):
        key = dict(zip(spec.stratum_fields, values, strict=True))
        baseline_group = baseline_groups.get(values)
        candidate_group = candidate_groups.get(values)
        if baseline_group is None or candidate_group is None:
            violations.append(
                ai_evaluation.EvaluationViolation(
                    code="evaluation_comparison_stratum_missing",
                    metric="stratum_coverage",
                    key={
                        **key,
                        "missing": "baseline" if baseline_group is None else "candidate",
                    },
                )
            )
            continue
        baseline_metrics = ai_evaluation.evaluate_records(
            baseline_group, spec.gate_policy.base_policy()
        ).metrics
        candidate_metrics = ai_evaluation.evaluate_records(
            candidate_group, spec.gate_policy.base_policy()
        ).metrics
        comparisons, comparison_violations = _compare_metrics(
            baseline_metrics,
            candidate_metrics,
            spec.max_metric_regression,
            key=key,
        )
        summaries.append(
            {
                "key": key,
                "metrics": {name: value.model_dump() for name, value in comparisons.items()},
            }
        )
        violations.extend(comparison_violations)
    return summaries, violations


def _groups(
    records: Sequence[ai_evaluation.EvaluationRecord], fields: tuple[str, ...]
) -> dict[tuple[str, ...], list[ai_evaluation.EvaluationRecord]]:
    grouped: dict[tuple[str, ...], list[ai_evaluation.EvaluationRecord]] = defaultdict(list)
    for record in records:
        grouped[tuple(str(getattr(record, field)) for field in fields)].append(record)
    return grouped


def _deduplicate(
    violations: Sequence[ai_evaluation.EvaluationViolation],
) -> list[ai_evaluation.EvaluationViolation]:
    unique: dict[str, ai_evaluation.EvaluationViolation] = {}
    for violation in violations:
        key = json.dumps(violation.model_dump(mode="json"), sort_keys=True)
        unique.setdefault(key, violation)
    return list(unique.values())


def _issue(code: str, draft: GeneratedQuestionDraft, **detail: str) -> EvaluationExportIssue:
    return EvaluationExportIssue(code=code, draft_id=str(draft.id), detail=detail)


def _serialize_records(records: Sequence[ai_evaluation.EvaluationRecord]) -> str:
    return "" if not records else "\n".join(record.model_dump_json() for record in records) + "\n"


def write_operational_artifacts(
    exported: EvaluationExportResult,
    report: OperationalEvaluationReport,
    output_directory: Path,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "records.jsonl").write_text(
        _serialize_records(exported.records), encoding="utf-8"
    )
    payloads = {
        "manifest.json": exported.manifest.model_dump(mode="json"),
        "export-issues.json": [issue.model_dump(mode="json") for issue in exported.issues],
        "report.json": report.model_dump(mode="json"),
    }
    for filename, payload in payloads.items():
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        (output_directory / filename).write_text(f"{rendered}\n", encoding="utf-8")
    report_json = json.dumps(
        report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True
    )
    html = (
        '<!doctype html>\n<html lang="en">\n<head><meta charset="utf-8">'
        "<title>Operational AI evaluation</title></head>\n"
        f"<body><h1>Operational AI evaluation</h1><pre>{escape(report_json)}</pre></body>\n"
        "</html>\n"
    )
    (output_directory / "report.html").write_text(html, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export production AI-authoring facts and compare explicit versions"
    )
    parser.add_argument("spec_path", type=Path)
    parser.add_argument("output_directory", type=Path)
    arguments = parser.parse_args(argv)
    spec = load_operational_spec(arguments.spec_path)
    with SessionLocal() as session:
        exported, report = run_operational_evaluation(session, spec)
    write_operational_artifacts(exported, report, arguments.output_directory)
    return 0 if report.promotion_eligible else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
