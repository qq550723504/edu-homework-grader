from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from test_question_verification import (
    Base,
    PassingGrader,
    PassingM2Grader,
    finding_codes,
    generation_draft,
    valid_m1_candidate,
    valid_m2_candidate,
    verify_current_revision,
)


_CORPUS_ROOT = Path(__file__).parent / "fixtures" / "verification_corpus"


def _corpus(question_type: str) -> dict[str, object]:
    payload = json.loads((_CORPUS_ROOT / f"{question_type.lower()}.json").read_text("utf-8"))

    assert payload["version"] == 1
    assert payload["question_type"] == question_type
    assert isinstance(payload["cases"], list)
    assert payload["cases"]
    return payload


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _CorpusM2Grader(PassingM2Grader):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        mathjson = answer_json["mathjson"]
        if mathjson in (["Add", "x", 1], ["Add", 1, "x"]):
            return {
                "type": "add",
                "args": [
                    {"type": "symbol", "name": "x"},
                    {"type": "number", "value": "1"},
                ],
            }
        if mathjson == ["Add", "x", 2]:
            return {
                "type": "add",
                "args": [
                    {"type": "symbol", "name": "x"},
                    {"type": "number", "value": "2"},
                ],
            }
        if mathjson == ["Multiply", "x", 1]:
            return {
                "type": "mul",
                "args": [
                    {"type": "symbol", "name": "x"},
                    {"type": "number", "value": "1"},
                ],
            }
        raise ValueError("unsupported deterministic MathJSON corpus input")


_M1_SCENARIOS = frozenset(
    {
        "correct",
        "numeric_equivalent",
        "whitespace_normalized",
        "zero_answer",
        "negative_decimal",
        "tolerance_boundaries",
        "fractional_tolerance",
        "large_integer",
        "incorrect",
        "common_misconception",
        "empty",
        "non_numeric_answer",
        "explanation_mismatch",
        "score_mismatch",
        "unexpected_mathjson",
        "missing_assertions",
        "boolean_score",
        "invalid_expected_rule",
        "negative_tolerance",
        "non_finite_tolerance",
    }
)

_M2_SCENARIOS = frozenset(
    {
        "correct",
        "alternate_display",
        "whitespace_mathjson",
        "commutative_normalization",
        "fractional_max_score",
        "higher_max_score",
        "incorrect",
        "common_misconception",
        "empty",
        "malformed_mathjson",
        "scalar_mathjson",
        "missing_assertions",
        "empty_answer_text",
        "null_mathjson",
        "explanation_mismatch",
        "score_mismatch",
        "invalid_score",
        "resource_limit",
        "unexpected_decision",
        "non_finite_score",
    }
)


def _m1_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _M1_SCENARIOS, f"unknown M1 corpus scenario: {scenario}"
    candidate = valid_m1_candidate("What is 2 + 2?")
    answer: object = "4"
    score: object = 1
    mathjson: object = None
    if scenario == "numeric_equivalent":
        answer = "4.0"
    elif scenario == "whitespace_normalized":
        answer = " 4 "
    elif scenario == "zero_answer":
        candidate["rule_json"] = {"expected": 0, "tolerance": 0}
        answer = "0"
    elif scenario == "negative_decimal":
        candidate["rule_json"] = {"expected": -2.5, "tolerance": 0}
        answer = "-2.5"
    elif scenario == "tolerance_boundaries":
        candidate["rule_json"] = {"expected": 2.5, "tolerance": 0.25}
        answer = "2.5"
    elif scenario == "fractional_tolerance":
        candidate["rule_json"] = {"expected": 1.25, "tolerance": 0.125}
        answer = "1.25"
    elif scenario == "large_integer":
        candidate["rule_json"] = {"expected": 123456, "tolerance": 0}
        answer = "123456"
    elif scenario == "incorrect":
        answer = "5"
    elif scenario == "common_misconception":
        answer = "6"
    elif scenario == "empty":
        answer = ""
    elif scenario == "non_numeric_answer":
        answer = "four"
    elif scenario == "score_mismatch":
        score = 2
    elif scenario == "unexpected_mathjson":
        mathjson = "[]"
    elif scenario == "boolean_score":
        score = True
    elif scenario == "invalid_expected_rule":
        candidate["rule_json"] = {"expected": "four", "tolerance": 0}
    elif scenario == "negative_tolerance":
        candidate["rule_json"] = {"expected": 4, "tolerance": -1}
    elif scenario == "non_finite_tolerance":
        candidate["rule_json"] = {"expected": 4, "tolerance": float("inf")}
    if scenario != "missing_assertions":
        candidate["verification_assertions"] = {
            "final_answer_text": answer,
            "final_answer_mathjson": mathjson,
            "declared_max_score": score,
        }
    candidate["explanation"] = f"Add the two whole numbers. Final answer: {answer}"
    if scenario == "explanation_mismatch":
        candidate["explanation"] = "Add the two whole numbers. Final answer: 5"
    return candidate


def _m2_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _M2_SCENARIOS, f"unknown M2 corpus scenario: {scenario}"
    candidate = valid_m2_candidate()
    mathjson: object = ["Add", "x", 1]
    text: object = "x + 1"
    score: object = 4
    if scenario == "alternate_display":
        text = "x + 1 (expanded)"
    elif scenario == "whitespace_mathjson":
        mathjson = '["Add", "x", 1]'
    elif scenario == "commutative_normalization":
        mathjson = ["Add", 1, "x"]
        text = "1 + x"
    elif scenario == "fractional_max_score":
        candidate["rule_json"] = {**candidate["rule_json"], "max_score": 0.9}
        score = 0.9
    elif scenario == "higher_max_score":
        candidate["rule_json"] = {**candidate["rule_json"], "max_score": 7}
        score = 7
    elif scenario == "incorrect":
        mathjson = ["Add", "x", 2]
        text = "x + 2"
    elif scenario == "common_misconception":
        mathjson = ["Multiply", "x", 1]
        text = "x"
    elif scenario == "empty":
        mathjson = ""
        text = ""
    elif scenario == "malformed_mathjson":
        mathjson = "["
    elif scenario == "scalar_mathjson":
        mathjson = "1"
    elif scenario == "empty_answer_text":
        text = ""
    elif scenario == "null_mathjson":
        mathjson = None
    elif scenario == "score_mismatch":
        score = 3
    elif scenario == "invalid_score":
        score = "four"
    if scenario != "missing_assertions":
        candidate["verification_assertions"] = {
            "final_answer_text": text,
            "final_answer_mathjson": (
                mathjson
                if isinstance(mathjson, str) or mathjson is None
                else json.dumps(mathjson, separators=(",", ":"))
            ),
            "declared_max_score": score,
        }
    candidate["explanation"] = f"The expression is already expanded. Final answer: {text}"
    if scenario == "explanation_mismatch":
        candidate["explanation"] = "The expression is already expanded. Final answer: x + 2"
    return candidate


@pytest.mark.parametrize(
    ("candidate_builder", "question_type"),
    [(_m1_candidate, "M1"), (_m2_candidate, "M2")],
)
def test_verification_corpus_rejects_unknown_scenarios(
    candidate_builder: object, question_type: str
) -> None:
    assert callable(candidate_builder)
    with pytest.raises(AssertionError, match=rf"unknown {question_type} corpus scenario"):
        candidate_builder("typo")


def _run_case(
    session: Session, question_type: str, case: dict[str, object]
) -> tuple[str, list[str]]:
    scenario = case["scenario"]
    assert isinstance(scenario, str)
    if question_type == "M1":
        draft = generation_draft(
            session,
            candidate_json=_m1_candidate(scenario),
            prompt_version="generator-v3",
        )
        run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())
    else:
        grader: PassingM2Grader
        if scenario == "resource_limit":
            grader = PassingM2Grader(failing_probe_index=4, failure_kind="exception")
        elif scenario == "unexpected_decision":
            grader = PassingM2Grader(failing_probe_index=1, failure_kind="unexpected_decision")
        elif scenario == "non_finite_score":
            grader = PassingM2Grader(failing_probe_index=0, failure_kind="non_finite_score")
        else:
            grader = _CorpusM2Grader()
        draft = generation_draft(
            session,
            allowed_question_types=["M2"],
            candidate_json=_m2_candidate(scenario),
            prompt_version="generator-v3",
        )
        run = verify_current_revision(session, draft=draft, grader_client=grader)
    return run.status.value, sorted(finding_codes(run))


def test_m1_m2_verification_corpus_runs_with_stable_type_summaries(session: Session) -> None:
    summary: list[str] = []
    for question_type in ("M1", "M2"):
        payload = _corpus(question_type)
        cases = payload["cases"]
        assert isinstance(cases, list)
        assert len(cases) >= 20, f"{question_type}: expected at least 20 deterministic cases"
        passed = 0
        finding_code_totals: Counter[str] = Counter()
        for case in cases:
            assert isinstance(case, dict)
            case_id = case.get("id")
            expected_status = case.get("expected_status")
            expected_codes = case.get("expected_codes")
            assert isinstance(case_id, str) and case_id
            assert isinstance(expected_status, str)
            assert isinstance(expected_codes, list) and all(
                isinstance(code, str) for code in expected_codes
            )
            status, codes = _run_case(session, question_type, case)
            assert status == expected_status, (
                f"{case_id}: expected status={expected_status}, actual status={status}, "
                f"finding_codes={codes}"
            )
            assert codes == expected_codes, (
                f"{case_id}: expected finding_codes={expected_codes}, actual finding_codes={codes}"
            )
            finding_code_totals.update(codes)
            passed += 1
        summary.extend(
            f"verification corpus findings: {question_type} code={code} total={total}"
            for code, total in sorted(finding_code_totals.items())
        )
        summary.append(
            f"verification corpus: {question_type} total={len(cases)} passed={passed} failed=0"
        )
    print("\n".join(summary))
