from uuid import uuid4

import pytest

from edu_generator.contracts import GeneratedCandidateEnvelope, GenerationRequest
from edu_generator.openai_provider import OpenAIResponsesProvider
from edu_generator.providers import FakeGenerationProvider, ProviderFailure


def test_fake_provider_returns_stable_m1_m2_e1_e4_envelopes() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        grade="Grade 5",
        subject="mathematics",
        question_types=["M1", "M2", "E1", "E4"],
        policy_version="2026.07",
        prompt_version="generator-v1",
        teacher_constraint="Use only whole numbers under 100.",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert [item.question_type for item in result.candidates] == [
        "M1",
        "M2",
        "E1",
        "E4",
    ]
    assert (
        GeneratedCandidateEnvelope.model_validate(result.model_dump()).candidates
        == result.candidates
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": "pilot"},
        {"candidates": [], "unexpected": True},
        {"candidates": [{"question_type": "M1"}]},
    ],
)
def test_candidate_envelope_rejects_identity_unknown_fields_and_incomplete_candidates(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ProviderFailure):
        GeneratedCandidateEnvelope.from_provider_payload(payload)


def test_openai_provider_requires_an_explicit_model_and_allowlisted_endpoint() -> None:
    with pytest.raises(ProviderFailure, match="GENERATOR_OPENAI_MODEL"):
        OpenAIResponsesProvider(
            api_key="test-key",
            model="",
            base_url="https://api.openai.com",
            allowed_hosts=frozenset({"api.openai.com"}),
        )

    with pytest.raises(ProviderFailure, match="allowlisted"):
        OpenAIResponsesProvider(
            api_key="test-key",
            model="gpt-test-snapshot",
            base_url="https://api.openai.com",
            allowed_hosts=frozenset({"other.example"}),
        )
