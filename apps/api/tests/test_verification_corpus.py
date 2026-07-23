from __future__ import annotations

import json
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
        if answer_json["mathjson"] == ["Add", "x", 2]:
            return {
                "type": "add",
                "args": [
                    {"type": "symbol", "name": "x"},
                    {"type": "number", "value": "2"},
                ],
            }
        return {
            "type": "add",
            "args": [
                {"type": "symbol", "name": "x"},
                {"type": "number", "value": "1"},
            ],
        }


def _m1_candidate(scenario: str) -> dict[str, object]:
    candidate = valid_m1_candidate("What is 2 + 2?")
    if scenario == "boundary":
        candidate["rule_json"] = {"expected": 2.5, "tolerance": 0.25}
        answer = "2.5"
    elif scenario in {"incorrect", "common_misconception"}:
        answer = "5"
    elif scenario == "empty":
        answer = ""
    else:
        answer = "4"
    candidate["verification_assertions"] = {
        "final_answer_text": answer,
        "final_answer_mathjson": None,
        "declared_max_score": 1,
    }
    candidate["explanation"] = f"Add the two whole numbers. Final answer: {answer}"
    return candidate


def _m2_candidate(scenario: str) -> dict[str, object]:
    candidate = valid_m2_candidate()
    mathjson: object = ["Add", "x", 1]
    text = "x + 1"
    score = 4
    if scenario in {"incorrect", "common_misconception"}:
        mathjson = ["Add", "x", 2]
        text = "x + 2"
    elif scenario == "empty":
        mathjson = ""
        text = ""
    candidate["verification_assertions"] = {
        "final_answer_text": text,
        "final_answer_mathjson": (
            mathjson if isinstance(mathjson, str) else json.dumps(mathjson, separators=(",", ":"))
        ),
        "declared_max_score": score,
    }
    candidate["explanation"] = f"The expression is already expanded. Final answer: {text}"
    return candidate


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
        grader = (
            PassingM2Grader(failing_probe_index=4, failure_kind="exception")
            if scenario == "resource_limit"
            else _CorpusM2Grader()
        )
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
        passed = 0
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
            assert status == expected_status, case_id
            assert codes == expected_codes, case_id
            passed += 1
        summary.append(
            f"verification corpus: {question_type} total={len(cases)} passed={passed} failed=0"
        )
    print("\n".join(summary))
