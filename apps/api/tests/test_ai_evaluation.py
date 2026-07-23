from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from edu_grader_api.services import ai_evaluation as evaluation


_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "ai_evaluation"


def _policy() -> evaluation.EvaluationPolicy:
    return evaluation.EvaluationPolicy.model_validate(
        {
            "policy_id": "ai-evaluation-policy-v1",
            "approved_model_ids": ["gpt-5.6-terra"],
            "approved_prompt_versions": ["generator-v3"],
            "thresholds": {
                "schema_pass_rate_min": 0.98,
                "math_answer_error_rate_max": 0.005,
                "grade_mismatch_rate_max": 0.02,
                "duplicate_or_similarity_rate_max": 0.03,
                "teacher_direct_accept_rate_min": 0.60,
                "teacher_modified_accept_rate_min": 0.85,
                "published_without_teacher_review_max": 0,
            },
        }
    )


def _passing_records() -> list[evaluation.EvaluationRecord]:
    outcomes = [
        ("M1", "accepted_directly"),
        ("M2", "accepted_after_edit"),
        ("E1", "accepted_directly"),
        ("E2", "accepted_directly"),
        ("E3", "accepted_after_edit"),
    ]
    return [
        evaluation.EvaluationRecord.model_validate(
            {
                "record_id": f"record-{index}",
                "run_id": "run-v1",
                "curriculum_profile": "cn-2022",
                "grade": "G7",
                "subject": "mathematics" if question_type.startswith("M") else "english",
                "question_type": question_type,
                "model_id": "gpt-5.6-terra",
                "prompt_version": "generator-v3",
                "validator_version": "verification-v5",
                "difficulty_band": "standard",
                "seed": index,
                "parameters": {"temperature": 0},
                "content_fingerprint": f"{index:064x}",
                "schema_valid": True,
                "math_answer_correct": True if question_type.startswith("M") else None,
                "grade_aligned": True,
                "duplicate_exact": False,
                "similarity_high": False,
                "teacher_outcome": teacher_outcome,
                "teacher_edited": teacher_outcome == "accepted_after_edit",
                "rejection_category": None,
                "published": True,
                "review_evidence": True,
                "cost_usd": 0.01,
                "duration_ms": 100,
            }
        )
        for index, (question_type, teacher_outcome) in enumerate(outcomes, start=1)
    ]


def _wrong_math_answer(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"math_answer_correct": False})
    return mutated


def _out_of_grade(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"grade_aligned": False})
    return mutated


def _duplicate_candidate(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"duplicate_exact": True})
    return mutated


def test_evaluate_records_passes_versioned_baseline_policy() -> None:
    report = evaluation.evaluate_records(_passing_records(), _policy())

    assert report.promotion_eligible is True
    assert report.violations == []
    assert report.rejection_reason_counts == {}
    assert report.cost_per_final_accepted_question == pytest.approx(0.01)
    assert report.end_to_end_duration_ms == {"average": 100.0, "maximum": 100}


def test_load_policy_reads_versioned_policy_fixture() -> None:
    policy = evaluation.load_policy(_FIXTURE_DIRECTORY / "policy-v1.json")

    assert policy.policy_id == "ai-evaluation-policy-v1"
    assert policy.approved_model_ids == ["gpt-5.6-terra"]


def test_load_records_reports_line_without_candidate_contents(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    records_path.write_text('{"candidate_body":"secret candidate"}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="line 1") as error:
        evaluation.load_records(records_path)

    assert "secret candidate" not in str(error.value)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_wrong_math_answer, "evaluation_math_answer_error_rate_above_threshold"),
        (_out_of_grade, "evaluation_grade_mismatch_rate_above_threshold"),
        (_duplicate_candidate, "evaluation_similarity_rate_above_threshold"),
    ],
)
def test_evaluate_records_blocks_quality_regressions(mutate, code) -> None:
    report = evaluation.evaluate_records(mutate(_passing_records()), _policy())

    assert report.promotion_eligible is False
    assert code in {violation.code for violation in report.violations}
