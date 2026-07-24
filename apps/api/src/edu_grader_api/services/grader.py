from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import httpx
from edu_grader_processor_policy import assert_allowed_processor_url, assert_deidentified_payload

from ..settings import settings

from .questions import GradeResult


class MathAnswerNormalizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class GraderRequestTimeoutError(TimeoutError):
    """Stable internal dependency timeout without URLs or payload details."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"grader dependency timed out during {operation}")


@dataclass(frozen=True)
class EmbeddingDependencyVersion:
    id: str
    revision: str
    digest: str

    def as_dict(self) -> dict[str, str]:
        return {"id": self.id, "revision": self.revision, "digest": self.digest}


@dataclass(frozen=True)
class SemanticSimilarityResult:
    scores: list[float]
    embedding: EmbeddingDependencyVersion


class HttpGraderClient:
    """Synchronous adapter for the internal deterministic Grader service."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        path, payload = self._request(
            question_type,
            rule_json,
            answer_json,
            policy_version=policy_version,
        )
        response = self._post(path, payload, operation="grade")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("grader response must be an object")
        return GradeResult(
            decision=data["decision"],
            score=data["score"],
            evidence={
                key: value
                for key, value in data.items()
                if key not in {"decision", "score", "grader_version"}
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
            response = self._post(
                "/v1/normalize/mathjson",
                {"mathjson": mathjson, "variables": variables},
                operation="normalizer",
            )
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

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        payload = {"query": query, "comparisons": comparisons}
        response = self._post(
            "/v1/semantic-similarity",
            payload,
            operation="similarity",
        )
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("semantic similarity response is invalid")
        scores = data.get("scores")
        if not isinstance(scores, list) or len(scores) != len(comparisons):
            raise ValueError("semantic similarity response is invalid")
        if any(
            isinstance(score, bool)
            or not isinstance(score, int | float)
            or not math.isfinite(score)
            or score < 0
            or score > 1
            for score in scores
        ):
            raise ValueError("semantic similarity response is invalid")
        embedding = _embedding_dependency_version(data.get("embedding"))
        return SemanticSimilarityResult(
            scores=[float(score) for score in scores],
            embedding=embedding,
        )

    def _post(
        self,
        path: str,
        payload: dict[str, object],
        *,
        operation: str,
    ) -> httpx.Response:
        self._validate_request(payload)
        try:
            response = httpx.post(
                f"{self.base_url}{path}",
                json=payload,
                timeout=settings.grader_request_timeout_seconds,
            )
        except httpx.TimeoutException as error:
            raise GraderRequestTimeoutError(operation) from error
        response.raise_for_status()
        return response

    def _validate_request(self, payload: dict[str, object]) -> None:
        assert_allowed_processor_url(self.base_url, settings.allowed_processor_hosts)
        assert_deidentified_payload(payload)

    def _request(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None,
    ) -> tuple[str, dict[str, Any]]:
        if question_type == "M2":
            return _mathjson_request(rule_json, answer_json)
        if question_type in {"E1", "E2", "E3", "E4"}:
            return _english_request(question_type, rule_json, answer_json, policy_version)
        if question_type != "M1":
            raise ValueError(f"question type {question_type} has no HTTP grader adapter")
        answer = _text_answer(answer_json)
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


def _english_request(
    question_type: str,
    rule_json: dict[str, object],
    answer_json: dict[str, object],
    policy_version: str | None,
) -> tuple[str, dict[str, Any]]:
    answer = _text_answer(answer_json)
    if not policy_version:
        raise ValueError(f"{question_type} rules require a grading policy version")
    return (
        "/v1/grade/english",
        {
            "question_type": question_type,
            "policy_version": policy_version,
            "rule": rule_json,
            "answer": {"answer": answer},
        },
    )


def _mathjson_request(
    rule_json: dict[str, object], answer_json: dict[str, object]
) -> tuple[str, dict[str, Any]]:
    expected = rule_json.get("expected")
    if isinstance(expected, bool) or not isinstance(expected, list | str | int | float):
        raise ValueError("M2@2 rules require a MathJSON expected value")
    if "mathjson" not in answer_json:
        raise ValueError("M2@2 answers require MathJSON")
    student_mathjson = answer_json["mathjson"]
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


def _embedding_dependency_version(value: object) -> EmbeddingDependencyVersion:
    if not isinstance(value, dict):
        raise ValueError("semantic similarity response is invalid")
    fields = {field: value.get(field) for field in ("id", "revision", "digest")}
    if not all(isinstance(item, str) and item.strip() for item in fields.values()):
        raise ValueError("semantic similarity response is invalid")
    return EmbeddingDependencyVersion(
        id=fields["id"].strip(),  # type: ignore[union-attr]
        revision=fields["revision"].strip(),  # type: ignore[union-attr]
        digest=fields["digest"].strip(),  # type: ignore[union-attr]
    )


def _text_answer(answer_json: dict[str, object]) -> str:
    if answer_json.get("format") != "text-v1":
        raise ValueError("text answers require the text-v1 answer envelope")
    text = answer_json.get("text")
    if not isinstance(text, str):
        raise ValueError("text answers require a text string")
    return text
