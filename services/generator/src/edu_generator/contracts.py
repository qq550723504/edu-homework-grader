from __future__ import annotations

from typing import Literal
from uuid import UUID

from edu_grader_processor_policy import (
    ProcessorPolicyError,
    assert_deidentified_payload,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError


QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"]


class ProviderFailure(RuntimeError):
    """A stable, sanitized provider failure that callers can safely persist."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class GenerationRequest(BaseModel):
    """The de-identified and bounded input allowed across the model boundary."""

    model_config = ConfigDict(extra="forbid")

    objective_revision_id: UUID
    grade: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=100)
    question_types: list[QuestionType] = Field(min_length=1, max_length=20)
    policy_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)

    def model_post_init(self, __context: object) -> None:
        try:
            assert_deidentified_payload(self.model_dump(mode="json"))
        except ProcessorPolicyError as exc:
            raise ValueError("generation request must be de-identified") from exc


class GeneratedCandidate(BaseModel):
    """Strict platform candidate schema shared by every model provider."""

    model_config = ConfigDict(extra="forbid")

    objective_revision_id: UUID
    question_type: QuestionType
    policy_version: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=10_000)
    rule_json: dict[str, object]
    explanation: str = Field(min_length=1, max_length=4_000)
    knowledge_point: str = Field(min_length=1, max_length=200)
    difficulty: float = Field(ge=0, le=1)


class GeneratedCandidateEnvelope(BaseModel):
    """Validated provider output; it remains a candidate until teacher review."""

    model_config = ConfigDict(extra="forbid")

    provider_name: str = Field(min_length=1, max_length=100)
    model_version: str = Field(min_length=1, max_length=200)
    candidates: list[GeneratedCandidate] = Field(min_length=1, max_length=20)

    @classmethod
    def from_provider_payload(
        cls, payload: dict[str, object]
    ) -> "GeneratedCandidateEnvelope":
        try:
            assert_deidentified_payload(payload)
            return cls.model_validate(payload)
        except (ProcessorPolicyError, ValidationError) as exc:
            raise ProviderFailure(
                "invalid_structured_output", "provider output failed validation"
            ) from exc
