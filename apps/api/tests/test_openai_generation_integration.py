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


def test_openai_responses_provider_returns_generator_v3_representative_batch() -> None:
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
            objective_text=(
                "Create concise grade-appropriate mathematics and English homework questions."
            ),
            knowledge_point="whole-number arithmetic, algebra, and short English comprehension",
            difficulty_min=0,
            difficulty_max=0.8,
            grade="Grade 7",
            subject="mathematics and English",
            items=[
                GenerationPlanItem(
                    question_type="M1",
                    difficulty_band="foundation",
                    target_difficulty=0.2,
                ),
                GenerationPlanItem(
                    question_type="M2",
                    difficulty_band="standard",
                    target_difficulty=0.5,
                ),
                GenerationPlanItem(
                    question_type="E1",
                    difficulty_band="foundation",
                    target_difficulty=0.2,
                ),
                GenerationPlanItem(
                    question_type="E4",
                    difficulty_band="standard",
                    target_difficulty=0.5,
                ),
            ],
            requested_count=4,
            policy_version="2026.07",
            prompt_version="generator-v3",
            teacher_constraint=(
                "Return one concise candidate for every requested type. Use elementary algebra "
                "and short original English material."
            ),
        )
    )

    assert [candidate.question_type for candidate in result.candidates] == [
        "M1",
        "M2",
        "E1",
        "E4",
    ]
    m1, m2, e1, e4 = result.candidates
    assert m1.verification_assertions is not None
    assert m1.verification_assertions.final_answer_mathjson is None
    assert m2.verification_assertions is not None
    assert m2.verification_assertions.final_answer_mathjson is not None
    assert e1.verification_assertions is None
    assert e4.verification_assertions is None
    assert e4.reading_material is not None and e4.reading_material.strip()
