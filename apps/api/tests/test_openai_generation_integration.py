from __future__ import annotations

import os
from uuid import uuid4

import pytest

from edu_generator.contracts import GenerationPlanItem, GenerationRequest
from edu_generator.openai_provider import OpenAIResponsesProvider


pytestmark = pytest.mark.skipif(
    os.environ.get("LIVE_OPENAI_GENERATION") != "1"
    or not os.environ.get("OPENAI_API_KEY")
    or not os.environ.get("GENERATOR_OPENAI_MODEL"),
    reason="requires explicit controlled OpenAI integration configuration",
)


def test_openai_responses_provider_returns_one_schema_valid_candidate() -> None:
    provider = OpenAIResponsesProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        model=os.environ["GENERATOR_OPENAI_MODEL"],
        base_url=os.environ.get("GENERATOR_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        allowed_hosts=frozenset(
            item.strip().casefold()
            for item in os.environ.get("GENERATOR_PROVIDER_ALLOWED_HOSTS", "api.openai.com").split(
                ","
            )
            if item.strip()
        ),
    )

    result = provider.generate(
        GenerationRequest(
            objective_revision_id=uuid4(),
            objective_text="Add whole numbers below ten.",
            difficulty_min=0,
            difficulty_max=0.3,
            grade="Grade 5",
            subject="mathematics",
            items=[
                GenerationPlanItem(
                    question_type="M1",
                    difficulty_band="standard",
                    target_difficulty=0.2,
                )
            ],
            requested_count=1,
            policy_version="2026.07",
            prompt_version="generator-v1",
            teacher_constraint="Use only whole numbers below ten.",
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].question_type == "M1"
