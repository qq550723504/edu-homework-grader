from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from edu_grader_api.services import ai_evaluation
from edu_grader_api.services import ai_evaluation_gate


_FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "ai_evaluation"


def _policy() -> ai_evaluation_gate.GatePolicy:
    return ai_evaluation_gate.load_policy(_FIXTURE_DIRECTORY / "policy-v1.json")


def _records() -> list[ai_evaluation.EvaluationRecord]:
    return ai_evaluation.load_records(_FIXTURE_DIRECTORY / "golden-v1.jsonl")


def _codes(report: ai_evaluation.EvaluationReport) -> set[str]:
    return {violation.code for violation in report.violations}


def test_gate_accepts_complete_six_type_baseline() -> None:
    records = _records()

    report = ai_evaluation_gate.evaluate_records(records, _policy())

    assert Counter(record.question_type for record in records) == {
        "M1": 20,
        "M2": 20,
        "E1": 20,
        "E2": 20,
        "E3": 20,
        "E4": 20,
    }
    assert report.promotion_eligible is True
    assert report.violations == []


def test_gate_blocks_empty_evidence() -> None:
    report = ai_evaluation_gate.evaluate_records([], _policy())

    assert report.promotion_eligible is False
    assert "evaluation_insufficient_evidence" in _codes(report)
    assert "evaluation_insufficient_review_evidence" in _codes(report)


def test_gate_blocks_missing_required_question_type() -> None:
    records = [record for record in _records() if record.question_type != "E4"]

    report = ai_evaluation_gate.evaluate_records(records, _policy())

    assert report.promotion_eligible is False
    matching = [
        violation
        for violation in report.violations
        if violation.code == "evaluation_insufficient_evidence"
        and violation.key.get("question_type") == "E4"
    ]
    assert matching


def test_gate_blocks_insufficient_reviewed_records() -> None:
    records = deepcopy(_records())
    for index, record in enumerate(records):
        if record.question_type == "E1":
            records[index] = record.model_copy(
                update={
                    "teacher_outcome": "pending_review",
                    "teacher_edited": False,
                    "published": False,
                    "review_evidence": False,
                }
            )

    report = ai_evaluation_gate.evaluate_records(records, _policy())

    assert report.promotion_eligible is False
    assert any(
        violation.code == "evaluation_insufficient_review_evidence"
        and violation.key.get("question_type") == "E1"
        for violation in report.violations
    )


def test_gate_blocks_cross_field_state_contradictions() -> None:
    records = deepcopy(_records())
    records[0] = records[0].model_copy(
        update={"teacher_outcome": "accepted_after_edit", "teacher_edited": False}
    )
    records[1] = records[1].model_copy(
        update={
            "teacher_outcome": "rejected",
            "teacher_edited": False,
            "rejection_category": "incorrect_answer",
            "published": True,
            "review_evidence": True,
        }
    )
    english_index = next(
        index for index, record in enumerate(records) if record.question_type == "E1"
    )
    records[english_index] = records[english_index].model_copy(
        update={"math_answer_correct": True}
    )

    report = ai_evaluation_gate.evaluate_records(records, _policy())

    reasons = {
        violation.key.get("reason")
        for violation in report.violations
        if violation.code == "evaluation_record_state_invalid"
    }
    assert {
        "edited_accept_missing_edit",
        "rejected_record_published",
        "publication_without_acceptance",
        "english_record_has_math_answer_result",
    }.issubset(reasons)


def test_gate_main_writes_blocking_artifacts_for_empty_input(tmp_path: Path) -> None:
    records_path = tmp_path / "empty.jsonl"
    output_directory = tmp_path / "report"
    records_path.write_text("", encoding="utf-8")

    exit_code = ai_evaluation_gate.main(
        [
            str(_FIXTURE_DIRECTORY / "policy-v1.json"),
            str(records_path),
            str(output_directory),
        ]
    )

    assert exit_code == 1
    report = json.loads((output_directory / "report.json").read_text(encoding="utf-8"))
    assert report["promotion_eligible"] is False
    assert any(
        violation["code"] == "evaluation_insufficient_evidence"
        for violation in report["violations"]
    )
    assert (output_directory / "report.html").is_file()
