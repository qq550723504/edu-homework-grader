from __future__ import annotations

import json

from edu_grader_processor_policy import (
    ProcessorPolicyError,
    assert_allowed_processor_url,
)
from pydantic import ValidationError

from .contracts import (
    GeneratedCandidateEnvelope,
    GenerationRequest,
    ProviderCandidatePayload,
    ProviderFailure,
)


class OpenAIResponsesProvider:
    """OpenAI Responses adapter isolated from Core API business services."""

    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        allowed_hosts: frozenset[str],
        timeout_seconds: float = 30,
    ) -> None:
        if not api_key:
            raise ProviderFailure(
                "provider_not_configured", "OPENAI_API_KEY is required"
            )
        if not model:
            raise ProviderFailure(
                "provider_not_configured", "GENERATOR_OPENAI_MODEL is required"
            )
        try:
            assert_allowed_processor_url(base_url, allowed_hosts)
        except ProcessorPolicyError as exc:
            raise ProviderFailure(
                "provider_url_not_allowed", "OpenAI endpoint is not allowlisted"
            ) from exc
        self.api_key = api_key
        self.model_version = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, request: GenerationRequest) -> GeneratedCandidateEnvelope:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ProviderFailure(
                "provider_unavailable", "OpenAI provider dependency is unavailable"
            ) from exc

        try:
            client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
            response = client.responses.create(
                model=self.model_version,
                instructions=(
                    "Generate de-identified candidate homework questions. "
                    "Return only JSON conforming to the supplied schema."
                ),
                input=json.dumps(request.model_dump(mode="json"), ensure_ascii=True),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "generated_question_candidates",
                        "strict": True,
                        "schema": ProviderCandidatePayload.model_json_schema(),
                    }
                },
            )
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str):
                raise ProviderFailure(
                    "invalid_structured_output", "OpenAI returned no structured output"
                )
            payload = ProviderCandidatePayload.model_validate_json(output_text)
        except ProviderFailure:
            raise
        except ValidationError as exc:
            raise ProviderFailure(
                "invalid_structured_output",
                "OpenAI output failed structured validation",
            ) from exc
        except Exception as exc:
            raise _classify_openai_error(exc) from exc

        return GeneratedCandidateEnvelope(
            provider_name=self.provider_name,
            model_version=self.model_version,
            candidates=payload.candidates,
        )


def _classify_openai_error(error: Exception) -> ProviderFailure:
    error_name = type(error).__name__
    if error_name in {
        "APITimeoutError",
        "APIConnectionError",
        "RateLimitError",
        "InternalServerError",
    }:
        return ProviderFailure(
            "provider_transient_failure",
            "OpenAI request failed transiently",
            retryable=True,
        )
    return ProviderFailure("provider_request_failed", "OpenAI request failed")
