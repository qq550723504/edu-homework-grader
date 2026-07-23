from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from test_question_verification import (
    Base,
    FailingE2Grader,
    FailingE3Grader,
    FailingE4Grader,
    FailingGrader,
    MalformedE3FeedbackGrader,
    MissingSemanticGrader,
    NonFiniteE4Grader,
    PassingGrader,
    PassingE2Grader,
    PassingE3Grader,
    PassingE4Grader,
    PassingM2Grader,
    PartialE2Grader,
    PartialE4Grader,
    UnexpectedE3DecisionGrader,
    UnexpectedE4DecisionGrader,
    SafeAstM2Grader,
    SemanticGrader,
    add_published_question,
    finding_codes,
    generation_draft,
    valid_e2_candidate,
    valid_e3_candidate,
    valid_e4_candidate,
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
        "grader_failure",
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
        "deep_safe_ast",
        "resource_limit",
        "unexpected_decision",
        "non_finite_score",
    }
)

_E1_SCENARIOS = frozenset(
    {
        "correct",
        "two_distinct",
        "unicode_distinct",
        "punctuation_distinct",
        "number_answer",
        "normalized_duplicate",
        "casefold_duplicate",
        "unicode_duplicate",
        "empty_list",
        "empty_answer",
        "whitespace_answer",
        "non_string",
        "long_answer",
        "missing_answers",
        "unexpected_rule_key",
        "null_answers",
        "three_distinct",
        "mixed_script_distinct",
        "linebreak_normalized_duplicate",
        "nbsp_normalized_duplicate",
    }
)

_E2_SCENARIOS = frozenset(
    {
        "correct",
        "two_forms",
        "punctuation_variant",
        "unicode_distinct",
        "alternate_lemma",
        "normalized_duplicate",
        "casefold_duplicate",
        "unicode_duplicate",
        "empty_list",
        "empty_form",
        "long_form",
        "missing_forms",
        "invalid_lemma",
        "extra_rule_key",
        "grader_exception",
        "partial_score",
        "higher_max_score",
        "forms_with_space",
        "three_distinct",
        "linebreak_duplicate",
    }
)

_E3_SCENARIOS = frozenset(
    {
        "clean",
        "no_reference",
        "two_references",
        "grammar_warning",
        "multiple_grammar_warnings",
        "grader_exception",
        "unexpected_decision",
        "malformed_feedback",
        "dependency_feedback",
        "empty_prompt",
        "invalid_reference",
        "empty_reference",
        "long_reference",
        "extra_rule_key",
        "false_grammar_flag",
        "true_grammar_flag",
        "short_prompt",
        "three_references",
        "warning_with_reference",
        "unicode_prompt",
    }
)

_E4_SCENARIOS = frozenset(
    {
        "correct",
        "single_point",
        "fractional_score",
        "material_whitespace",
        "duplicate_id",
        "empty_phrase",
        "duplicate_phrase",
        "overlapping_phrase",
        "score_mismatch",
        "non_finite_score",
        "missing_material",
        "blank_material",
        "long_material",
        "evidence_mismatch",
        "grader_exception",
        "unexpected_decision",
        "partial_score",
        "grader_non_finite",
        "extra_rule_key",
        "empty_points",
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


def _e1_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _E1_SCENARIOS, f"unknown E1 corpus scenario: {scenario}"
    candidate: dict[str, object] = {
        "question_type": "E1",
        "policy_version": "2",
        "prompt": "Choose the correct color.",
        "rule_json": {"accepted_answers": ["blue"]},
        "explanation": "Choose the matching color word.",
    }
    rule = candidate["rule_json"]
    assert isinstance(rule, dict)
    if scenario == "two_distinct":
        rule["accepted_answers"] = ["blue", "red"]
    elif scenario == "unicode_distinct":
        rule["accepted_answers"] = ["café", "cafe"]
    elif scenario == "punctuation_distinct":
        rule["accepted_answers"] = ["go!", "go?"]
    elif scenario == "number_answer":
        rule["accepted_answers"] = ["12"]
    elif scenario == "normalized_duplicate":
        rule["accepted_answers"] = ["blue", " blue "]
    elif scenario == "casefold_duplicate":
        rule["accepted_answers"] = ["Blue", "blue"]
    elif scenario == "unicode_duplicate":
        rule["accepted_answers"] = ["blue", "ＢＬＵＥ"]
    elif scenario == "empty_list":
        rule["accepted_answers"] = []
    elif scenario == "empty_answer":
        rule["accepted_answers"] = [""]
    elif scenario == "whitespace_answer":
        rule["accepted_answers"] = [" "]
    elif scenario == "non_string":
        rule["accepted_answers"] = [1]
    elif scenario == "long_answer":
        rule["accepted_answers"] = ["a" * 2001]
    elif scenario == "missing_answers":
        candidate["rule_json"] = {}
    elif scenario == "unexpected_rule_key":
        rule["unexpected"] = True
    elif scenario == "null_answers":
        rule["accepted_answers"] = None
    elif scenario == "three_distinct":
        rule["accepted_answers"] = ["blue", "red", "green"]
    elif scenario == "mixed_script_distinct":
        rule["accepted_answers"] = ["blue", "蓝色"]
    elif scenario == "linebreak_normalized_duplicate":
        rule["accepted_answers"] = ["blue sky", "blue\nsky"]
    elif scenario == "nbsp_normalized_duplicate":
        rule["accepted_answers"] = ["blue sky", "blue\u00a0sky"]
    return candidate


def _e2_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _E2_SCENARIOS, f"unknown E2 corpus scenario: {scenario}"
    candidate = valid_e2_candidate()
    rule = candidate["rule_json"]
    assert isinstance(rule, dict)
    if scenario == "two_forms":
        rule["accepted_forms"] = ["went", "did go"]
    elif scenario == "punctuation_variant":
        rule["accepted_forms"] = ["went.", "gone!"]
    elif scenario == "unicode_distinct":
        rule["accepted_forms"] = ["went", "wenté"]
    elif scenario == "alternate_lemma":
        rule["lemma"] = "write"
        rule["accepted_forms"] = ["wrote"]
    elif scenario == "normalized_duplicate":
        rule["accepted_forms"] = ["went", " went "]
    elif scenario == "casefold_duplicate":
        rule["accepted_forms"] = ["Went", "went"]
    elif scenario == "unicode_duplicate":
        rule["accepted_forms"] = ["went", "ｗｅｎｔ"]
    elif scenario == "empty_list":
        rule["accepted_forms"] = []
    elif scenario == "empty_form":
        rule["accepted_forms"] = [""]
    elif scenario == "long_form":
        rule["accepted_forms"] = ["a" * 257]
    elif scenario == "missing_forms":
        candidate["rule_json"] = {"lemma": "go"}
    elif scenario == "invalid_lemma":
        rule["lemma"] = ""
    elif scenario == "extra_rule_key":
        rule["unexpected"] = True
    elif scenario == "higher_max_score":
        rule["max_score"] = 2
    elif scenario == "forms_with_space":
        rule["accepted_forms"] = ["went ", "gone"]
    elif scenario == "three_distinct":
        rule["accepted_forms"] = ["went", "did go", "had gone"]
    elif scenario == "linebreak_duplicate":
        rule["accepted_forms"] = ["went home", "went\nhome"]
    return candidate


def _e3_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _E3_SCENARIOS, f"unknown E3 corpus scenario: {scenario}"
    candidate = valid_e3_candidate()
    rule = candidate["rule_json"]
    assert isinstance(rule, dict)
    if scenario == "no_reference" or scenario == "grammar_warning":
        rule.pop("accepted_answers")
    elif scenario == "two_references":
        rule["accepted_answers"] = ["I walked home.", "We visited the library."]
    elif scenario == "invalid_reference":
        rule["accepted_answers"] = [1]
    elif scenario == "empty_reference":
        rule["accepted_answers"] = [""]
    elif scenario == "long_reference":
        rule["accepted_answers"] = ["a" * 2001]
    elif scenario == "extra_rule_key":
        rule["unexpected"] = True
    elif scenario == "false_grammar_flag":
        rule["grammar_feedback_required"] = False
    elif scenario == "true_grammar_flag":
        rule["grammar_feedback_required"] = True
    elif scenario == "short_prompt":
        candidate["prompt"] = "Write."
    elif scenario == "three_references":
        rule["accepted_answers"] = ["I walked home.", "We visited the library.", "They ate lunch."]
    elif scenario == "warning_with_reference":
        rule["accepted_answers"] = ["I walked home."]
    elif scenario == "unicode_prompt":
        candidate["prompt"] = "Write one sentence about café visits."
    elif scenario == "empty_prompt":
        candidate["prompt"] = ""
    return candidate


def _e4_candidate(scenario: str) -> dict[str, object]:
    assert scenario in _E4_SCENARIOS, f"unknown E4 corpus scenario: {scenario}"
    candidate = valid_e4_candidate()
    rule = candidate["rule_json"]
    assert isinstance(rule, dict)
    points = rule["scoring_points"]
    assert isinstance(points, list)
    if scenario == "single_point":
        rule["max_score"] = 1
        rule["scoring_points"] = [
            {"id": "reason", "evidence_phrases": ["bridge was closed"], "score": 1}
        ]
        candidate["reading_material"] = "The bridge was closed, so they arrived late."
    elif scenario == "fractional_score":
        rule["max_score"] = 0.9
        points[0]["score"] = 0.7
        points[1]["score"] = 0.2
    elif scenario == "material_whitespace":
        candidate["reading_material"] = "Because   the bridge was closed,\n they arrived late."
    elif scenario == "duplicate_id":
        points[1]["id"] = " reason "
    elif scenario == "empty_phrase":
        points[1]["evidence_phrases"] = ["  "]
    elif scenario == "duplicate_phrase":
        points[1]["evidence_phrases"] = [" Because the bridge was closed. "]
    elif scenario == "overlapping_phrase":
        points[0]["evidence_phrases"] = ["bridge closed"]
        points[1]["evidence_phrases"] = ["closed"]
        candidate["reading_material"] = "The bridge closed, and they arrived late."
    elif scenario == "score_mismatch":
        rule["max_score"] = 4
    elif scenario == "non_finite_score":
        rule["max_score"] = float("nan")
    elif scenario == "missing_material":
        candidate.pop("reading_material")
    elif scenario == "blank_material":
        candidate["reading_material"] = " "
    elif scenario == "long_material":
        candidate["reading_material"] = "a" * 8001
    elif scenario == "evidence_mismatch":
        candidate["reading_material"] = "The road was open, and they arrived early."
    elif scenario == "extra_rule_key":
        rule["unexpected"] = True
    elif scenario == "empty_points":
        rule["scoring_points"] = []
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
) -> tuple[str, list[str], str]:
    scenario = case["scenario"]
    assert isinstance(scenario, str)
    if question_type == "M1":
        draft = generation_draft(
            session,
            candidate_json=_m1_candidate(scenario),
            prompt_version="generator-v3",
        )
        grader = FailingGrader() if scenario == "grader_failure" else PassingGrader()
        run = verify_current_revision(session, draft=draft, grader_client=grader)
    elif question_type == "M2":
        grader: PassingM2Grader
        if scenario == "resource_limit":
            grader = PassingM2Grader(failing_probe_index=4, failure_kind="exception")
        elif scenario == "deep_safe_ast":
            ast: dict[str, object] = {"type": "symbol", "name": "x"}
            for _ in range(21):
                ast = {"type": "neg", "arg": ast}
            grader = SafeAstM2Grader(ast)
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
    elif question_type == "E1":
        draft = generation_draft(
            session, allowed_question_types=["E1"], candidate_json=_e1_candidate(scenario)
        )
        run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())
    elif question_type == "E2":
        grader: PassingE2Grader
        if scenario == "grader_exception":
            grader = FailingE2Grader()
        elif scenario == "partial_score":
            grader = PartialE2Grader()
        else:
            grader = PassingE2Grader()
        draft = generation_draft(
            session, allowed_question_types=["E2"], candidate_json=_e2_candidate(scenario)
        )
        run = verify_current_revision(session, draft=draft, grader_client=grader)
    elif question_type == "E3":
        grader: PassingE3Grader
        if scenario == "grader_exception":
            grader = FailingE3Grader()
        elif scenario == "unexpected_decision":
            grader = UnexpectedE3DecisionGrader()
        elif scenario == "malformed_feedback":
            grader = MalformedE3FeedbackGrader()
        elif scenario == "dependency_feedback":
            grader = PassingE3Grader([{"type": "dependency"}])
        elif scenario in {"grammar_warning", "warning_with_reference"}:
            grader = PassingE3Grader([{"type": "grammar"}])
        elif scenario == "multiple_grammar_warnings":
            grader = PassingE3Grader([{"type": "grammar"}, {"type": "grammar"}])
        else:
            grader = PassingE3Grader()
        draft = generation_draft(
            session, allowed_question_types=["E3"], candidate_json=_e3_candidate(scenario)
        )
        run = verify_current_revision(session, draft=draft, grader_client=grader)
    else:
        assert question_type == "E4"
        grader: PassingE4Grader
        if scenario == "grader_exception":
            grader = FailingE4Grader()
        elif scenario == "unexpected_decision":
            grader = UnexpectedE4DecisionGrader()
        elif scenario == "partial_score":
            grader = PartialE4Grader()
        elif scenario == "grader_non_finite":
            grader = NonFiniteE4Grader()
        else:
            grader = PassingE4Grader()
        draft = generation_draft(
            session, allowed_question_types=["E4"], candidate_json=_e4_candidate(scenario)
        )
        run = verify_current_revision(session, draft=draft, grader_client=grader)
    return run.status.value, sorted(finding_codes(run)), draft.teacher_state


def test_m1_m2_verification_corpus_runs_with_stable_type_summaries(session: Session) -> None:
    summary: list[str] = []
    for question_type in ("M1", "M2", "E1", "E2", "E3", "E4"):
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
            expected_teacher_state = case.get("expected_teacher_state")
            assert isinstance(case_id, str) and case_id
            assert isinstance(expected_status, str)
            assert isinstance(expected_codes, list) and all(
                isinstance(code, str) for code in expected_codes
            )
            assert expected_teacher_state is None or isinstance(expected_teacher_state, str)
            status, codes, teacher_state = _run_case(session, question_type, case)
            assert status == expected_status, (
                f"{case_id}: expected status={expected_status}, actual status={status}, "
                f"finding_codes={codes}"
            )
            assert codes == expected_codes, (
                f"{case_id}: expected finding_codes={expected_codes}, actual finding_codes={codes}"
            )
            if expected_teacher_state is not None:
                assert teacher_state == expected_teacher_state, (
                    f"{case_id}: expected teacher_state={expected_teacher_state}, "
                    f"actual teacher_state={teacher_state}"
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


def test_similarity_dependency_corpus_blocks_without_candidate_contents(session: Session) -> None:
    payload = _corpus("similarity")
    cases = payload["cases"]
    assert isinstance(cases, list) and cases
    for case in cases:
        assert isinstance(case, dict)
        case_id = case.get("id")
        scenario = case.get("scenario")
        expected_codes = case.get("expected_codes")
        assert isinstance(case_id, str) and case_id
        assert isinstance(scenario, str)
        assert isinstance(expected_codes, list) and all(
            isinstance(code, str) for code in expected_codes
        )
        draft = generation_draft(
            session, candidate_json=valid_m1_candidate("Calculate two plus two.")
        )
        add_published_question(session, draft=draft, prompt="Name the capital of France.")
        if scenario == "missing_client":
            grader = MissingSemanticGrader()
        elif scenario == "empty_scores":
            grader = SemanticGrader([[]])
        elif scenario == "non_finite_score":
            grader = SemanticGrader([[float("nan")]])
        elif scenario == "timeout":
            grader = SemanticGrader([RuntimeError("private similarity timeout")])
        else:
            raise AssertionError(f"unknown similarity corpus scenario: {scenario}")
        run = verify_current_revision(session, draft=draft, grader_client=grader)
        codes = sorted(finding_codes(run))
        assert run.status.value == "blocked", f"{case_id}: status={run.status.value}, codes={codes}"
        assert codes == expected_codes, f"{case_id}: expected={expected_codes}, actual={codes}"
        assert "Calculate two plus two." not in str(run.findings)
        assert "Name the capital of France." not in str(run.findings)
