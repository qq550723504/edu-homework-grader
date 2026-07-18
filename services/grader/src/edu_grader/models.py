from typing import Literal

from pydantic import BaseModel, Field

Decision = Literal[
    "auto_accepted",
    "auto_rejected",
    "partial",
    "needs_review",
    "grading_error",
    "unsupported",
]


class Criterion(BaseModel):
    code: str
    score: float = Field(ge=0)
    max_score: float = Field(ge=0)
    passed: bool
    evidence: str


class Feedback(BaseModel):
    type: str
    message: str


class GradingResult(BaseModel):
    decision: Decision
    score: float = Field(ge=0)
    max_score: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    criteria: list[Criterion]
    feedback: list[Feedback] = Field(default_factory=list)
    requires_review: bool = False
    grader_version: str = "grader-0.1.0"
