from __future__ import annotations

from collections.abc import Mapping

from .english import grade_english_rule, normalize_answer
from .english_dependencies import (
    EnglishDependencyError,
    GrammarChecker,
    GrammarMatch,
    SemanticSimilarity,
)
from .models import Criterion, Feedback, GradingResult


class NoopGrammarChecker:
    def check(self, text: str) -> list[GrammarMatch]:
        return []


class StaticGrammarChecker:
    def __init__(self, matches: list[GrammarMatch]) -> None:
        self._matches = matches

    def check(self, text: str) -> list[GrammarMatch]:
        return self._matches


def grade_english(
    request: Mapping[str, object],
    *,
    grammar_checker: GrammarChecker,
    similarity: SemanticSimilarity,
) -> GradingResult:
    question_type = request.get("question_type")
    policy_version = request.get("policy_version")
    if question_type in {"E1", "E2"}:
        return grade_english_rule(request)
    if question_type == "E3" and policy_version == "1":
        return _grade_e3(request, grammar_checker)
    if question_type == "E4" and policy_version == "2":
        return _grade_e4(request, similarity)
    return _review_result("unsupported_rule", "English rule is unsupported.")


def _grade_e3(request: Mapping[str, object], grammar_checker: GrammarChecker) -> GradingResult:
    rule, answer = _rule_and_answer(request)
    if rule is None or answer is None:
        return _review_result("invalid_request", "English rule and answer must be objects.")
    max_score = _max_score(rule)
    feedback: list[Feedback] = []
    signals: list[dict[str, object]] = []
    if rule.get("grammar_feedback_required") is True:
        try:
            matches = grammar_checker.check(answer)
        except EnglishDependencyError as error:
            return _review_result("grammar_dependency", str(error), max_score=max_score)
        feedback = [_grammar_feedback(match) for match in matches]
        signals = [_grammar_signal(match) for match in matches]
    return GradingResult(
        decision="needs_review",
        score=0.0,
        max_score=max_score,
        confidence=0.0,
        criteria=[
            Criterion(
                code="grammar_assistance",
                score=0.0,
                max_score=max_score,
                passed=False,
                evidence="grammar feedback requires teacher review",
            )
        ],
        feedback=feedback,
        signals=signals,
        requires_review=True,
    )


def _grade_e4(request: Mapping[str, object], similarity: SemanticSimilarity) -> GradingResult:
    rule, answer = _rule_and_answer(request)
    if rule is None or answer is None:
        return _review_result("invalid_request", "English rule and answer must be objects.")
    points = rule.get("scoring_points")
    if not isinstance(points, list):
        return _review_result(
            "invalid_rule", "E4@2 requires scoring points.", max_score=_max_score(rule)
        )
    threshold = rule.get("similarity_threshold", 0.78)
    if isinstance(threshold, bool) or not isinstance(threshold, int | float):
        return _review_result(
            "invalid_rule", "E4@2 similarity threshold is invalid.", max_score=_max_score(rule)
        )
    normalized_answer = normalize_answer(answer, ignore_case=True, ignore_terminal_punctuation=True)
    criteria: list[Criterion] = []
    signals: list[dict[str, object]] = []
    provisional_score = 0.0
    for point in points:
        if not isinstance(point, Mapping):
            return _review_result(
                "invalid_rule", "E4@2 scoring point is invalid.", max_score=_max_score(rule)
            )
        point_id = point.get("id")
        phrases = point.get("evidence_phrases")
        point_score = point.get("score")
        if (
            not isinstance(point_id, str)
            or not isinstance(phrases, list)
            or isinstance(point_score, bool)
            or not isinstance(point_score, int | float)
        ):
            return _review_result(
                "invalid_rule", "E4@2 scoring point is invalid.", max_score=_max_score(rule)
            )
        normalized_phrases = [
            normalize_answer(phrase, ignore_case=True, ignore_terminal_punctuation=True)
            for phrase in phrases
            if isinstance(phrase, str)
        ]
        matched_phrase = next(
            (phrase for phrase in normalized_phrases if phrase and phrase in normalized_answer),
            None,
        )
        try:
            similarities = [
                similarity.score(normalized_answer, phrase) for phrase in normalized_phrases
            ]
        except EnglishDependencyError as error:
            return _review_result("similarity_dependency", str(error), max_score=_max_score(rule))
        highest_similarity = max(similarities, default=0.0)
        passed = matched_phrase is not None
        awarded = float(point_score) if passed else 0.0
        provisional_score += awarded
        criteria.append(
            Criterion(
                code=point_id,
                score=awarded,
                max_score=float(point_score),
                passed=passed,
                evidence=(
                    f"matched scoring-point evidence: {matched_phrase}"
                    if passed
                    else "no scoring-point evidence matched"
                ),
            )
        )
        signals.append(
            {
                "kind": "scoring_point",
                "code": point_id,
                "matched_evidence": matched_phrase,
                "highest_similarity": highest_similarity,
                "similarity_threshold": float(threshold),
                "similarity_at_or_above_threshold": highest_similarity >= float(threshold),
            }
        )
    return GradingResult(
        decision="needs_review",
        score=provisional_score,
        max_score=_max_score(rule),
        confidence=0.0,
        criteria=criteria,
        signals=signals,
        requires_review=True,
    )


def _rule_and_answer(
    request: Mapping[str, object],
) -> tuple[Mapping[str, object] | None, str | None]:
    rule = request.get("rule")
    answer = request.get("answer")
    if not isinstance(rule, Mapping) or not isinstance(answer, Mapping):
        return None, None
    text = answer.get("answer")
    return rule, text if isinstance(text, str) else None


def _max_score(rule: Mapping[str, object]) -> float:
    value = rule.get("max_score", 1)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return 1.0
    return float(value)


def _grammar_feedback(match: GrammarMatch) -> Feedback:
    return Feedback(
        type="grammar",
        message=match.message,
        offset=match.offset,
        length=match.length,
        rule_id=match.rule_id,
        category=match.category,
        issue_type=match.issue_type,
        replacements=match.replacements,
    )


def _grammar_signal(match: GrammarMatch) -> dict[str, object]:
    return {
        "kind": "grammar",
        "code": match.rule_id,
        "offset": match.offset,
        "length": match.length,
        "category": match.category,
        "issue_type": match.issue_type,
        "replacements": match.replacements,
    }


def _review_result(code: str, message: str, *, max_score: float = 1.0) -> GradingResult:
    return GradingResult(
        decision="needs_review",
        score=0.0,
        max_score=max_score,
        confidence=0.0,
        criteria=[
            Criterion(code=code, score=0.0, max_score=max_score, passed=False, evidence=message)
        ],
        feedback=[Feedback(type="dependency", message=message)],
        requires_review=True,
    )
