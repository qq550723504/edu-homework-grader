from __future__ import annotations

from typing import Any

import httpx

from .questions import GradeResult


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

    def _request(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
    ) -> tuple[str, dict[str, Any]]:
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
