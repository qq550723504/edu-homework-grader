import re
import unicodedata

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
) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _WHITESPACE.sub(" ", normalized.strip())
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
            []
            if matched
            else [Feedback(type="answer", message="答案未匹配教师配置的可接受答案。")]
        ),
    )
