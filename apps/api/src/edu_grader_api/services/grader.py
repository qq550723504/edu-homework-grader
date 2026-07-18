from __future__ import annotations

from typing import Any

import httpx

from .questions import GradeResult


class MathAnswerNormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class HttpGraderClient:
    """Synchronous adapter for the internal deterministic Grader service."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
    ) -> GradeResult:
        path, payload = self._request(question_type, rule_json, answer_json)
        response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return GradeResult(
            decision=data["decision"],
            score=data["score"],
            evidence={
                "criteria": data.get("criteria", []),
                "requires_review": data.get("requires_review", False),
            },
            grader_version=data["grader_version"],
        )

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        mathjson = answer_json.get("mathjson")
        if mathjson is None:
            raise MathAnswerNormalizationError("missing_mathjson", "数学答案缺少 MathJSON。")
        variables = answer_json.get("variables", [])
        if not isinstance(variables, list) or not all(
            isinstance(variable, str) for variable in variables
        ):
            raise MathAnswerNormalizationError("invalid_variables", "数学答案变量列表无效。")
        try:
            response = httpx.post(
                f"{self.base_url}/v1/normalize/mathjson",
                json={"mathjson": mathjson, "variables": variables},
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            payload = _error_payload(error)
            raise MathAnswerNormalizationError(
                str(payload.get("code", "normalization_failed")),
                str(payload.get("message", "数学表达式无法规范化。")),
            ) from error
        data = response.json()
        ast = data.get("ast")
        if not isinstance(ast, dict):
            raise MathAnswerNormalizationError(
                "invalid_normalizer_response", "数学规范化服务响应无效。"
            )
        return ast

    def _request(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
    ) -> tuple[str, dict[str, Any]]:
        if question_type == "M2":
            return _mathjson_request(rule_json, answer_json)
        if question_type != "M1":
            raise ValueError(f"question type {question_type} has no HTTP grader adapter")
        answer = answer_json.get("answer")
        if not isinstance(answer, str):
            raise ValueError("M1 test answers require an answer string")
        expected = rule_json.get("expected")
        if not isinstance(expected, int | float):
            raise ValueError("M1 rules require a numeric expected value")
        tolerance = rule_json.get("tolerance", 0)
        if not isinstance(tolerance, int | float):
            raise ValueError("M1 rules require a numeric tolerance")
        return (
            "/v1/grade/math/numeric",
            {
                "student_answer": answer,
                "expected_answer": str(expected),
                "tolerance": str(tolerance),
            },
        )


def _mathjson_request(
    rule_json: dict[str, object], answer_json: dict[str, object]
) -> tuple[str, dict[str, Any]]:
    expected = rule_json.get("expected")
    if isinstance(expected, bool) or not isinstance(expected, list | str | int | float):
        raise ValueError("M2@2 rules require a MathJSON expected value")
    answer = answer_json.get("answer")
    student_mathjson = answer.get("mathjson") if isinstance(answer, dict) else answer
    if student_mathjson is None:
        raise ValueError("M2@2 answers require MathJSON")
    variables = rule_json.get("variables", [])
    if not isinstance(variables, list) or not all(
        isinstance(variable, str) for variable in variables
    ):
        raise ValueError("M2@2 rules require a variables array")
    required_form = rule_json.get("required_form")
    if required_form not in {None, "expanded"}:
        raise ValueError("M2@2 rules require a supported required_form")
    form_score = rule_json.get("form_score", 0)
    max_score = rule_json.get("max_score", 1)
    if isinstance(form_score, bool) or not isinstance(form_score, int | float):
        raise ValueError("M2@2 rules require a numeric form_score")
    if isinstance(max_score, bool) or not isinstance(max_score, int | float):
        raise ValueError("M2@2 rules require a numeric max_score")
    return (
        "/v1/grade/math/expression-v2",
        {
            "student_mathjson": student_mathjson,
            "expected_mathjson": expected,
            "variables": variables,
            "required_form": required_form,
            "form_score": form_score,
            "max_score": max_score,
        },
    )


def _error_payload(error: httpx.HTTPStatusError) -> dict[str, object]:
    try:
        payload = error.response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
