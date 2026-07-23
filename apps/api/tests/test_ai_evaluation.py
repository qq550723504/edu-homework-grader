from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
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
    records: list[evaluation.EvaluationRecord] = []
    for question_type in ("M1", "M2", "E1", "E2", "E3", "E4"):
        for index in range(20):
            teacher_outcome = (
                "accepted_directly"
                if index < 12
                else "accepted_after_edit"
                if index < 16
                else "rejected"
            )
            records.append(
                evaluation.EvaluationRecord.model_validate(
                    {
                        "record_id": f"{question_type.lower()}-record-{index}",
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
                        "content_fingerprint": f"{len(records):064x}",
                        "schema_valid": True,
                        "math_answer_correct": True if question_type.startswith("M") else None,
                        "grade_aligned": True,
                        "duplicate_exact": False,
                        "similarity_high": False,
                        "teacher_outcome": teacher_outcome,
                        "teacher_edited": teacher_outcome == "accepted_after_edit",
                        "rejection_category": "not_aligned"
                        if teacher_outcome == "rejected"
                        else None,
                        "published": teacher_outcome != "rejected",
                        "review_evidence": True,
                        "cost_usd": 0.01,
                        "duration_ms": 100,
                    }
                )
            )
    return records


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
    for index in range(3):
        mutated[index] = mutated[index].model_copy(update={"grade_aligned": False})
    return mutated


def _duplicate_candidate(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    for index in range(4):
        mutated[index] = mutated[index].model_copy(update={"duplicate_exact": True})
    return mutated


def _unapproved_model(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"model_id": "gpt-4o"})
    return mutated


def _unapproved_prompt(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"prompt_version": "generator-floating-v1"})
    return mutated


def _published_without_review(
    records: list[evaluation.EvaluationRecord],
) -> list[evaluation.EvaluationRecord]:
    mutated = deepcopy(records)
    mutated[0] = mutated[0].model_copy(update={"review_evidence": False})
    return mutated


def test_evaluate_records_passes_versioned_baseline_policy() -> None:
    report = evaluation.evaluate_records(_passing_records(), _policy())

    assert report.promotion_eligible is True
    assert report.violations == []
    assert report.rejection_reason_counts == {"not_aligned": 24}
    assert report.cost_per_final_accepted_question == pytest.approx(0.0125)
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


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_unapproved_model, "evaluation_unapproved_model"),
        (_unapproved_prompt, "evaluation_unapproved_prompt"),
        (_published_without_review, "evaluation_published_without_teacher_review"),
    ],
)
def test_evaluate_records_blocks_unapproved_versions_and_publication(mutate, code) -> None:
    report = evaluation.evaluate_records(mutate(_passing_records()), _policy())

    assert report.promotion_eligible is False
    assert code in {violation.code for violation in report.violations}


def test_evaluate_records_reports_versioned_strata_and_comparisons() -> None:
    records = _passing_records()
    records[0] = records[0].model_copy(
        update={"model_id": "gpt-5.6-sol", "prompt_version": "generator-v4"}
    )
    policy = _policy().model_copy(
        update={
            "approved_model_ids": ["gpt-5.6-sol", "gpt-5.6-terra"],
            "approved_prompt_versions": ["generator-v3", "generator-v4"],
        }
    )

    report = evaluation.evaluate_records(records, policy)

    assert len(report.version_summaries) == 2
    assert set(report.strata[0].key) == {
        "curriculum_profile",
        "grade",
        "subject",
        "question_type",
        "model_id",
        "prompt_version",
        "validator_version",
        "difficulty_band",
    }


def _write_records(path: Path, records: list[evaluation.EvaluationRecord]) -> None:
    path.write_text(
        "\n".join(record.model_dump_json() for record in records) + "\n", encoding="utf-8"
    )


def test_main_writes_json_and_html_for_passing_gate(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    output_directory = tmp_path / "report"
    _write_records(records_path, _passing_records())

    exit_code = evaluation.main(
        [str(_FIXTURE_DIRECTORY / "policy-v1.json"), str(records_path), str(output_directory)]
    )

    assert exit_code == 0
    report = json.loads((output_directory / "report.json").read_text(encoding="utf-8"))
    assert report["promotion_eligible"] is True
    html = (output_directory / "report.html").read_text(encoding="utf-8")
    assert "ai-evaluation-policy-v1" in html
    assert "schema_pass_rate" in html


def test_main_writes_artifacts_when_quality_gate_blocks(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    output_directory = tmp_path / "report"
    _write_records(records_path, _wrong_math_answer(_passing_records()))

    exit_code = evaluation.main(
        [str(_FIXTURE_DIRECTORY / "policy-v1.json"), str(records_path), str(output_directory)]
    )

    assert exit_code == 1
    assert (output_directory / "report.json").is_file()
    assert (output_directory / "report.html").is_file()


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (_wrong_math_answer, "evaluation_math_answer_error_rate_above_threshold"),
        (_out_of_grade, "evaluation_grade_mismatch_rate_above_threshold"),
        (_duplicate_candidate, "evaluation_similarity_rate_above_threshold"),
        (_unapproved_model, "evaluation_unapproved_model"),
        (_unapproved_prompt, "evaluation_unapproved_prompt"),
        (_published_without_review, "evaluation_published_without_teacher_review"),
    ],
)
def test_main_writes_artifacts_for_each_blocking_probe(tmp_path: Path, mutate, code) -> None:
    records_path = tmp_path / "records.jsonl"
    output_directory = tmp_path / "report"
    _write_records(records_path, mutate(_passing_records()))

    exit_code = evaluation.main(
        [str(_FIXTURE_DIRECTORY / "policy-v1.json"), str(records_path), str(output_directory)]
    )

    assert exit_code == 1
    report = json.loads((output_directory / "report.json").read_text(encoding="utf-8"))
    assert code in {violation["code"] for violation in report["violations"]}
    assert (output_directory / "report.html").is_file()


def test_golden_fixture_covers_six_types_without_sensitive_candidate_fields() -> None:
    fixture_path = _FIXTURE_DIRECTORY / "golden-v1.jsonl"
    records = evaluation.load_records(fixture_path)
    raw_records = [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = evaluation.evaluate_records(records, _policy())

    assert Counter(record.question_type for record in records) == {
        "M1": 20,
        "M2": 20,
        "E1": 20,
        "E2": 20,
        "E3": 20,
        "E4": 20,
    }
    assert report.promotion_eligible is True
    assert all(
        {"student", "student_answer", "candidate_body", "prompt"}.isdisjoint(record)
        for record in raw_records
    )
