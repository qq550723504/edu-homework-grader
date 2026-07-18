from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class CalibrationRecord(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    question_id: str = Field(min_length=1, max_length=200)
    question_type: Literal["E1", "E2", "E3", "E4"]
    rule: dict[str, object]
    student_answer: str = Field(max_length=2_000)
    predicted_decision: str = Field(min_length=1, max_length=30)
    predicted_score: float = Field(ge=0)
    human_decision: str = Field(min_length=1, max_length=30)
    human_score: float = Field(ge=0)
    human_scoring_point_ids: list[str] = Field(default_factory=list)
    expected_feedback_codes: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class CalibrationMetrics:
    error_release_rate: float
    revision_rate: float
    automatic_coverage: float


def load_calibration(path: Path) -> list[CalibrationRecord]:
    records: list[CalibrationRecord] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(CalibrationRecord.model_validate_json(line))
        except ValidationError as error:
            raise ValueError(f"invalid calibration record at line {number}: {error}") from error
    return records


def summarize_calibration(records: list[CalibrationRecord]) -> dict[str, CalibrationMetrics]:
    summary: dict[str, CalibrationMetrics] = {}
    for question_type in ("E1", "E2", "E3", "E4"):
        subset = [record for record in records if record.question_type == question_type]
        automatic_accepts = [
            record for record in subset if record.predicted_decision == "auto_accepted"
        ]
        releases = [
            record
            for record in automatic_accepts
            if record.human_decision != record.predicted_decision
            or record.human_score != record.predicted_score
        ]
        reviewed = [record for record in subset if record.predicted_decision == "needs_review"]
        revisions = [record for record in reviewed if record.human_score != record.predicted_score]
        automatic = [
            record
            for record in subset
            if record.predicted_decision in {"auto_accepted", "auto_rejected", "partial"}
        ]
        summary[question_type] = CalibrationMetrics(
            error_release_rate=_ratio(len(releases), len(automatic_accepts)),
            revision_rate=_ratio(len(revisions), len(reviewed)),
            automatic_coverage=0.0
            if question_type == "E4"
            else _ratio(len(automatic), len(subset)),
        )
    return summary


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main(argv: list[str] | None = None) -> int:
    arguments = argv if argv is not None else sys.argv[1:]
    if len(arguments) != 1:
        raise SystemExit("usage: python -m edu_grader.calibration PATH")
    metrics = summarize_calibration(load_calibration(Path(arguments[0])))
    print(json.dumps({key: asdict(value) for key, value in metrics.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
