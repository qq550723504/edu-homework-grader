import json
from types import SimpleNamespace
from uuid import uuid4

import openai
import pytest

from edu_generator.contracts import (
    GeneratedCandidate,
    GeneratedCandidateEnvelope,
    GenerationRequest,
    ProviderCandidatePayload,
)
from edu_generator.openai_provider import OpenAIResponsesProvider
from edu_generator.providers import FakeGenerationProvider, ProviderFailure


def test_fake_provider_returns_stable_m1_m2_e1_e4_envelopes() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        objective_text="Use whole numbers under 100.",
        difficulty_min=0,
        difficulty_max=1,
        grade="Grade 5",
        subject="mathematics",
        question_types=["M1", "M2", "E1", "E4"],
        requested_count=4,
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


def test_generated_candidate_requires_material_only_for_e4() -> None:
    base = {
        "objective_revision_id": str(uuid4()),
        "policy_version": "2",
        "prompt": "Read and answer.",
        "rule_json": {"scoring_points": []},
        "explanation": "Explain.",
        "knowledge_point": "reading",
        "difficulty": 0.5,
    }

    assert (
        GeneratedCandidate.model_validate(
            {
                **base,
                "question_type": "E4",
                "reading_material": "A complete response.",
            }
        ).reading_material
        == "A complete response."
    )
    with pytest.raises(
        ValueError, match="E4 candidates require nonblank reading_material"
    ):
        GeneratedCandidate.model_validate({**base, "question_type": "E4"})
    with pytest.raises(
        ValueError, match="only E4 candidates may include reading_material"
    ):
        GeneratedCandidate.model_validate(
            {**base, "question_type": "M1", "reading_material": "A passage."}
        )


def test_responses_schema_exposes_nullable_reading_material() -> None:
    candidate = ProviderCandidatePayload.model_json_schema()["$defs"][
        "GeneratedCandidate"
    ]

    assert candidate["properties"]["reading_material"]["anyOf"][1] == {"type": "null"}
    assert candidate["properties"]["reading_material"]["maxLength"] == 8_000


def test_openai_provider_sends_strict_reading_material_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outgoing = _capture_openai_request(monkeypatch)

    candidate = outgoing["text"]["format"]["schema"]["$defs"]["GeneratedCandidate"]

    assert "reading_material" in candidate["required"]
    assert candidate["properties"]["reading_material"]["anyOf"][1] == {"type": "null"}
    assert "default" not in candidate["properties"]["reading_material"]


def test_openai_provider_instructs_conditional_reading_material_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outgoing = _capture_openai_request(monkeypatch)

    assert (
        "E4 must return a nonblank generated reading_material containing every E4 "
        "evidence phrase; all other types must return reading_material null."
        in outgoing["instructions"]
    )


def test_fake_provider_emits_only_e4_reading_material() -> None:
    request = GenerationRequest(
        objective_revision_id=uuid4(),
        objective_text="Read and answer.",
        difficulty_min=0,
        difficulty_max=1,
        grade="Grade 5",
        subject="English",
        question_types=["M1", "E4"],
        requested_count=2,
        policy_version="2026.07",
        prompt_version="generator-v1",
    )

    result = FakeGenerationProvider(seed=7).generate(request)

    assert result.candidates[0].reading_material is None
    assert "complete response" in (result.candidates[1].reading_material or "")


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


def _capture_openai_request(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    outgoing: dict[str, object] = {}
    objective_revision_id = uuid4()
    output_text = json.dumps(
        {
            "candidates": [
                {
                    "objective_revision_id": str(objective_revision_id),
                    "question_type": "M1",
                    "policy_version": "1",
                    "prompt": "What is 2 + 2?",
                    "rule_json": {"expected": 4, "tolerance": 0},
                    "explanation": "Add the two numbers.",
                    "knowledge_point": "addition",
                    "difficulty": 0.1,
                    "reading_material": None,
                }
            ]
        }
    )

    class FakeResponses:
        def create(self, **kwargs: object) -> SimpleNamespace:
            outgoing.update(kwargs)
            return SimpleNamespace(output_text=output_text)

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **_kwargs: SimpleNamespace(responses=FakeResponses()),
    )
    provider = OpenAIResponsesProvider(
        api_key="test-key",
        model="gpt-test-snapshot",
        base_url="https://api.openai.com",
        allowed_hosts=frozenset({"api.openai.com"}),
    )
    provider.generate(
        GenerationRequest(
            objective_revision_id=objective_revision_id,
            objective_text="Use whole numbers under 100.",
            difficulty_min=0,
            difficulty_max=1,
            grade="Grade 5",
            subject="mathematics",
            question_types=["M1"],
            requested_count=1,
            policy_version="1",
            prompt_version="generator-v1",
        )
    )
    return outgoing
