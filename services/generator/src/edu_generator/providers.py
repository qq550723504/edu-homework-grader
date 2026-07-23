from __future__ import annotations

from hashlib import sha256
import json
from typing import Protocol

from .contracts import (
    GeneratedCandidateEnvelope,
    GenerationRequest,
    ProviderFailure,
)


class GenerationProvider(Protocol):
    """A provider adapter that can return only the strict candidate envelope."""

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope: ...


class FakeGenerationProvider:
    """Deterministic, local provider for contract and orchestration tests."""

    provider_name = "fake"
    model_version = "fake-v1"

    def __init__(self, *, seed: int) -> None:
        self.seed = seed

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope:
        candidates = []
        for ordinal, item in enumerate(request.items, start=1):
            question_type = item.question_type
            stable_value = self._stable_value(request, ordinal)
            rule_json = _rule_for(question_type, stable_value)
            candidates.append(
                {
                    "objective_revision_id": str(request.objective_revision_id),
                    "question_type": question_type,
                    "policy_version": _default_policy_version_for(question_type),
                    "prompt": f"{request.subject} {question_type} practice item {stable_value}.",
                    "rule_json": rule_json,
                    "explanation": (
                        f"Generated for {request.grade} using objective practice. "
                        f"Final answer: {stable_value}"
                    ),
                    "knowledge_point": f"{request.subject} objective practice",
                    "difficulty": item.target_difficulty,
                    "verification_assertions": _verification_assertions(
                        question_type, rule_json, stable_value
                    ),
                    "reading_material": (
                        "The student gave a complete response about the practice item."
                        if question_type == "E4"
                        else None
                    ),
                }
            )
        return GeneratedCandidateEnvelope.from_provider_payload(
            {
                "provider_name": self.provider_name,
                "model_version": self.model_version,
                "candidates": candidates,
            }
        )

    def _stable_value(self, request: GenerationRequest, ordinal: int) -> int:
        material = f"{self.seed}:{request.objective_revision_id}:{ordinal}".encode()
        return int.from_bytes(sha256(material).digest()[:2], "big") % 100 + 1


def _rule_for(question_type: str, stable_value: int) -> dict[str, object]:
    if question_type == "M1":
        return {"expected": stable_value, "tolerance": 0}
    if question_type == "M2":
        return {"expected": str(stable_value)}
    if question_type == "E1":
        return {"accepted_answers": [str(stable_value)]}
    if question_type == "E2":
        return {"lemma": "practice", "accepted_forms": ["practice"]}
    if question_type == "E3":
        return {"grammar_feedback_required": True}
    return {
        "scoring_points": [
            {
                "id": "complete_response",
                "evidence_phrases": ["complete response"],
                "score": 1,
            }
        ]
    }


def _verification_assertions(
    question_type: str, rule_json: dict[str, object], stable_value: int
) -> dict[str, object] | None:
    if question_type == "M1":
        return {
            "final_answer_text": str(stable_value),
            "final_answer_mathjson": None,
            "declared_max_score": 1,
        }
    if question_type == "M2":
        return {
            "final_answer_text": str(stable_value),
            "final_answer_mathjson": json.dumps(
                rule_json["expected"], separators=(",", ":")
            ),
            "declared_max_score": float(rule_json.get("max_score", 1)),
        }
    return None


def _default_policy_version_for(question_type: str) -> str:
    return {"M1": "1", "M2": "2", "E1": "2", "E2": "1", "E3": "1", "E4": "2"}[
        question_type
    ]


__all__ = ["FakeGenerationProvider", "GenerationProvider", "ProviderFailure"]
