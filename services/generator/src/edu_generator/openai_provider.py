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
from .model_snapshots import validate_immutable_openai_model_id
from .prompt_templates import resolve_prompt_template


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
            model = validate_immutable_openai_model_id(model)
        except ValueError as exc:
            raise ProviderFailure(
                "provider_model_not_pinned",
                "OpenAI model must use an immutable model ID",
            ) from exc
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
            template = resolve_prompt_template(
                request.prompt_version, [item.question_type for item in request.items]
            )
        except ValueError as exc:
            raise ProviderFailure(
                "provider_prompt_template_unavailable",
                "Prompt template is not available for this request",
            ) from exc
        try:
            from openai import OpenAI
            from openai.lib._pydantic import to_strict_json_schema
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
            schema = to_strict_json_schema(ProviderCandidatePayload)
            schema["$defs"]["GeneratedCandidate"]["properties"]["rule_json"] = {
                "type": "string"
            }
            response = client.responses.create(
                model=self.model_version,
                instructions=template.system_instructions,
                input=json.dumps(request.model_dump(mode="json"), ensure_ascii=True),
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "generated_question_candidates",
                        "strict": True,
                        # Responses accepts a schema document, not a schema-version
                        # parameter; this strict schema is cataloged as template.schema_version.
                        "schema": schema,
                    }
                },
            )
            output_text = getattr(response, "output_text", None)
            if not isinstance(output_text, str):
                raise ProviderFailure(
                    "invalid_structured_output", "OpenAI returned no structured output"
                )
            payload = ProviderCandidatePayload.model_validate(
                _decode_rule_json_strings(output_text)
            )
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


def _decode_rule_json_strings(output_text: str) -> object:
    """Restore arbitrary rule objects from a strict-schema-safe string boundary."""

    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ProviderFailure(
            "invalid_structured_output", "OpenAI output failed structured validation"
        ) from exc

    if not isinstance(payload, dict):
        return payload
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        return payload

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        rule_json = candidate.get("rule_json")
        if not isinstance(rule_json, str):
            continue
        try:
            decoded_rule_json = json.loads(rule_json)
        except json.JSONDecodeError as exc:
            raise ProviderFailure(
                "invalid_structured_output",
                "OpenAI output failed structured validation",
            ) from exc
        if not isinstance(decoded_rule_json, dict):
            raise ProviderFailure(
                "invalid_structured_output",
                "OpenAI output failed structured validation",
            )
        candidate["rule_json"] = decoded_rule_json

    return payload
