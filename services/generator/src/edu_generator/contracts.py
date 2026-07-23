from __future__ import annotations

from typing import Literal
from uuid import UUID

from edu_grader_processor_policy import (
    ProcessorPolicyError,
    assert_deidentified_payload,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


QuestionType = Literal["M1", "M2", "E1", "E2", "E3", "E4"]
DifficultyBand = Literal["foundation", "standard", "stretch"]


class ProviderFailure(RuntimeError):
    """A stable, sanitized provider failure that callers can safely persist."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GenerationPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_type: QuestionType
    difficulty_band: DifficultyBand
    target_difficulty: float = Field(ge=0, le=1)


class GenerationRequest(BaseModel):
    """The de-identified and bounded input allowed across the model boundary."""

    model_config = ConfigDict(extra="forbid")

    objective_revision_id: UUID
    objective_text: str = Field(min_length=1, max_length=2_000)
    knowledge_point: str | None = Field(default=None, max_length=200)
    difficulty_min: float = Field(ge=0, le=1)
    difficulty_max: float = Field(ge=0, le=1)
    grade: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=100)
    items: list[GenerationPlanItem] = Field(min_length=1, max_length=20)
    requested_count: int = Field(ge=1, le=20)
    policy_version: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    teacher_constraint: str | None = Field(default=None, max_length=1_000)

    @model_validator(mode="after")
    def _validate_item_count(self) -> "GenerationRequest":
        if len(self.items) != self.requested_count:
            raise ValueError("generation plan item count must equal requested_count")
        return self

    def model_post_init(self, __context: object) -> None:
        try:
            assert_deidentified_payload(self.model_dump(mode="json"))
        except ProcessorPolicyError as exc:
            raise ValueError("generation request must be de-identified") from exc


class VerificationAssertions(BaseModel):
    """Structured declarations used by deterministic candidate verification."""

    model_config = ConfigDict(extra="forbid")

    final_answer_text: str = Field(min_length=1, max_length=2_000)
    final_answer_mathjson: str | None = Field(default=None, max_length=20_000)
    declared_max_score: float = Field(gt=0, le=100)


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
    verification_assertions: VerificationAssertions | None = None
    reading_material: str | None = Field(
        default=None, max_length=8_000, json_schema_extra={"maxLength": 8_000}
    )

    @model_validator(mode="after")
    def _validate_reading_material(self) -> "GeneratedCandidate":
        if self.question_type == "E4":
            if self.reading_material is None or not self.reading_material.strip():
                raise ValueError("E4 candidates require nonblank reading_material")
        elif self.reading_material is not None:
            raise ValueError("only E4 candidates may include reading_material")
        if self.verification_assertions is not None:
            if self.question_type not in {"M1", "M2"}:
                raise ValueError(
                    "only M1 and M2 candidates may include verification assertions"
                )
            if (
                self.question_type == "M1"
                and self.verification_assertions.final_answer_mathjson is not None
            ):
                raise ValueError(
                    "M1 verification assertions require null final_answer_mathjson"
                )
            if (
                self.question_type == "M2"
                and self.verification_assertions.final_answer_mathjson is None
            ):
                raise ValueError(
                    "M2 verification assertions require final_answer_mathjson"
                )
        return self


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


class ProviderCandidatePayload(BaseModel):
    """The provider-authored portion of a Responses structured output."""

    model_config = ConfigDict(extra="forbid")

    candidates: list[GeneratedCandidate] = Field(min_length=1, max_length=20)
