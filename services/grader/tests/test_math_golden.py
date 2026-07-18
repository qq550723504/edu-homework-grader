import json
from pathlib import Path

import pytest

from edu_grader.math_ast import grade_mathjson_expression


_FIXTURE = Path(__file__).parent / "fixtures" / "m2_mathjson_golden.json"


def _golden_cases() -> list[dict[str, object]]:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_golden_suite_has_broad_fixed_coverage() -> None:
    cases = _golden_cases()

    assert len(cases) >= 100
    assert {case["category"] for case in cases} >= {
        "accepted",
        "partial",
        "incorrect",
        "boundary",
        "invalid",
        "adversarial",
    }


@pytest.mark.parametrize("case", _golden_cases(), ids=lambda case: str(case["name"]))
def test_mathjson_golden_case(case: dict[str, object]) -> None:
    result = grade_mathjson_expression(
        student_mathjson=case["student"],
        expected_mathjson=case["expected"],
        variables=case["variables"],
        required_form=case["required_form"],
        form_score=case["form_score"],
        max_score=case["max_score"],
    )

    assert result.decision == case["decision"]
    assert result.score == case["score"]
    assert result.criteria[0].code == case["criterion_code"]
    assert result.requires_review is (result.decision == "needs_review")
