from pathlib import Path

from edu_grader.calibration import CalibrationRecord, load_calibration, summarize_calibration


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "english_calibration.jsonl"


def test_calibration_fixture_has_one_thousand_answers_for_one_hundred_questions() -> None:
    records = load_calibration(FIXTURE_PATH)

    assert len(records) >= 1_000
    assert len({record.question_id for record in records}) >= 100


def test_metrics_group_by_type_and_exclude_e4_from_automatic_coverage() -> None:
    summary = summarize_calibration(
        [
            CalibrationRecord(
                id="e1-1",
                question_id="q1",
                question_type="E1",
                rule={},
                student_answer="cat",
                predicted_decision="auto_accepted",
                predicted_score=1,
                human_decision="auto_rejected",
                human_score=0,
                human_scoring_point_ids=[],
                expected_feedback_codes=[],
            ),
            CalibrationRecord(
                id="e4-1",
                question_id="q2",
                question_type="E4",
                rule={},
                student_answer="answer",
                predicted_decision="needs_review",
                predicted_score=0,
                human_decision="needs_review",
                human_score=1,
                human_scoring_point_ids=["cause"],
                expected_feedback_codes=[],
            ),
        ]
    )

    assert summary["E1"].error_release_rate == 1.0
    assert summary["E1"].automatic_coverage == 1.0
    assert summary["E4"].automatic_coverage == 0.0
    assert summary["E4"].revision_rate == 1.0
