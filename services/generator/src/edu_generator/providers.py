from __future__ import annotations

from hashlib import sha256
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
        for ordinal, question_type in enumerate(request.question_types, start=1):
            stable_value = self._stable_value(request, ordinal)
            candidates.append(
                {
                    "objective_revision_id": str(request.objective_revision_id),
                    "question_type": question_type,
                    "policy_version": request.policy_version,
                    "prompt": f"{request.subject} {question_type} practice item {stable_value}.",
                    "rule_json": {"expected_answer": str(stable_value)},
                    "explanation": f"Generated for {request.grade} using objective practice.",
                    "knowledge_point": f"{request.subject} objective practice",
                    "difficulty": round(((stable_value % 7) + 1) / 10, 1),
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


__all__ = ["FakeGenerationProvider", "GenerationProvider", "ProviderFailure"]
