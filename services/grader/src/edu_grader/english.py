import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, Field

from .models import Criterion, Feedback, GradingResult

_WHITESPACE = re.compile(r"\s+")
_TERMINAL_PUNCTUATION = re.compile(r"[.!?。！？]+$")


class EnglishExactRequest(BaseModel):
    student_answer: str = Field(max_length=2_000)
    accepted_answers: list[str] = Field(min_length=1, max_length=50)
    ignore_case: bool = True
    ignore_terminal_punctuation: bool = True
    max_score: float = Field(default=1, gt=0, le=100)


def normalize_answer(
    value: str,
    *,
    ignore_case: bool,
    ignore_terminal_punctuation: bool,
    collapse_whitespace: bool = True,
) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.strip()
    if collapse_whitespace:
        normalized = _WHITESPACE.sub(" ", normalized)
    if ignore_terminal_punctuation:
        normalized = _TERMINAL_PUNCTUATION.sub("", normalized).rstrip()
    if ignore_case:
        normalized = normalized.casefold()
    return normalized


def grade_exact(request: EnglishExactRequest) -> GradingResult:
    student = normalize_answer(
        request.student_answer,
        ignore_case=request.ignore_case,
        ignore_terminal_punctuation=request.ignore_terminal_punctuation,
    )
    accepted = {
        normalize_answer(
            answer,
            ignore_case=request.ignore_case,
            ignore_terminal_punctuation=request.ignore_terminal_punctuation,
        )
        for answer in request.accepted_answers
    }

    matched = bool(student) and student in accepted
    score = request.max_score if matched else 0.0

    return GradingResult(
        decision="auto_accepted" if matched else "auto_rejected",
        score=score,
        max_score=request.max_score,
        confidence=1.0,
        criteria=[
            Criterion(
                code="accepted_answer",
                score=score,
                max_score=request.max_score,
                passed=matched,
                evidence=(
                    "Normalized answer matched an accepted answer."
                    if matched
                    else "Normalized answer did not match an accepted answer."
                ),
            )
        ],
        feedback=(
            [] if matched else [Feedback(type="answer", message="答案未匹配教师配置的可接受答案。")]
        ),
    )


def grade_english_rule(request: Mapping[str, object]) -> GradingResult:
    """Grade deterministic E1/E2 English rules without external dependencies."""

    question_type = request.get("question_type")
    policy_version = request.get("policy_version")
    rule = request.get("rule")
    answer = request.get("answer")
    if not isinstance(question_type, str) or not isinstance(policy_version, str):
        return _unsupported_result("English rule requires a question type and policy version.")
    if not isinstance(rule, Mapping) or not isinstance(answer, Mapping):
        return _unsupported_result("English rule and answer must be objects.")
    answer_text = answer.get("answer")
    if not isinstance(answer_text, str):
        return _unsupported_result("English answer must contain a string answer.")
    if question_type == "E1" and policy_version == "2":
        return _grade_e1_v2(rule, answer_text)
    if question_type == "E2" and policy_version == "1":
        return _grade_e2_v1(rule, answer_text)
    return _unsupported_result(
        f"Unsupported deterministic English rule {question_type}@{policy_version}."
    )


def _grade_e1_v2(rule: Mapping[str, object], answer: str) -> GradingResult:
    accepted_answers = _string_list(rule.get("accepted_answers"))
    if not accepted_answers:
        return _unsupported_result("E1@2 requires accepted answers.")
    normalization = rule.get("normalization", {})
    if not isinstance(normalization, Mapping):
        return _unsupported_result("E1@2 normalization must be an object.")
    settings = _normalization_settings(normalization)
    student = normalize_answer(answer, **settings)
    accepted = {
        normalize_answer(candidate, **settings)
        for candidate in accepted_answers
        if normalize_answer(candidate, **settings)
    }
    max_score = _max_score(rule)
    matched = bool(student) and student in accepted
    score = max_score if matched else 0.0
    return GradingResult(
        decision="auto_accepted" if matched else "auto_rejected",
        score=score,
        max_score=max_score,
        confidence=1.0,
        criteria=[
            Criterion(
                code="accepted_answer",
                score=score,
                max_score=max_score,
                passed=matched,
                evidence=(
                    f"matched accepted answer: {student}"
                    if matched
                    else "normalized answer did not match an accepted answer"
                ),
            )
        ],
        feedback=[]
        if matched
        else [Feedback(type="answer", message="答案未匹配教师配置的可接受答案。")],
    )


def _grade_e2_v1(rule: Mapping[str, object], answer: str) -> GradingResult:
    accepted_forms = _string_list(rule.get("accepted_forms"))
    if not accepted_forms:
        return _unsupported_result("E2@1 requires accepted forms.")
    student = normalize_answer(answer, ignore_case=True, ignore_terminal_punctuation=True)
    accepted = {
        normalize_answer(form, ignore_case=True, ignore_terminal_punctuation=True)
        for form in accepted_forms
    }
    max_score = _max_score(rule)
    matched = bool(student) and student in accepted
    score = max_score if matched else 0.0
    criteria = [
        Criterion(
            code="accepted_form",
            score=score,
            max_score=max_score,
            passed=matched,
            evidence=(
                "matched configured accepted form"
                if matched
                else "did not match a configured accepted form"
            ),
        )
    ]
    constraints = rule.get("constraints", {})
    if isinstance(constraints, Mapping):
        for name in ("part_of_speech", "tense", "number", "determiner"):
            required = constraints.get(name)
            if isinstance(required, str):
                criteria.append(
                    Criterion(
                        code=name,
                        score=0.0,
                        max_score=0.0,
                        passed=matched,
                        evidence=(
                            f"configured {name} constraint requires {required}"
                            if not matched
                            else f"configured {name} constraint satisfied"
                        ),
                    )
                )
    return GradingResult(
        decision="auto_accepted" if matched else "auto_rejected",
        score=score,
        max_score=max_score,
        confidence=1.0,
        criteria=criteria,
        feedback=[]
        if matched
        else [Feedback(type="form", message="答案不符合教师配置的词形规则。")],
    )


def _normalization_settings(values: Mapping[str, object]) -> dict[str, bool]:
    return {
        "ignore_case": values.get("ignore_case", True) is not False,
        "ignore_terminal_punctuation": values.get("ignore_terminal_punctuation", True) is not False,
        "collapse_whitespace": values.get("collapse_whitespace", True) is not False,
    }


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return value


def _max_score(rule: Mapping[str, object]) -> float:
    value = rule.get("max_score", 1)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return 1.0
    return float(value)


def _unsupported_result(message: str) -> GradingResult:
    return GradingResult(
        decision="unsupported",
        score=0.0,
        max_score=1.0,
        confidence=0.0,
        criteria=[
            Criterion(
                code="unsupported_rule", score=0.0, max_score=1.0, passed=False, evidence=message
            )
        ],
        feedback=[Feedback(type="rule", message=message)],
        requires_review=True,
    )
