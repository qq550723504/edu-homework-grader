"""Runtime registry for supported generation provider/model pairs."""

from edu_generator.contracts import ProviderFailure
from edu_generator.model_snapshots import validate_immutable_openai_model_id
from edu_generator.openai_provider import OpenAIResponsesProvider
from edu_generator.providers import FakeGenerationProvider, GenerationProvider

from ..settings import settings


def generation_provider(provider_name: str | None, model_version: str | None) -> GenerationProvider:
    """Build the same provider used by generation workers, or reject the pair."""

    if provider_name == "fake" and model_version == "fake-v1":
        return FakeGenerationProvider(seed=0)
    if provider_name == "openai" and model_version is not None:
        try:
            validate_immutable_openai_model_id(model_version)
        except ValueError as exc:
            raise ProviderFailure(
                "provider_not_configured", "generation provider is not configured"
            ) from exc
        return OpenAIResponsesProvider(
            api_key=settings.openai_api_key,
            model=model_version,
            base_url=settings.generator_openai_base_url,
            allowed_hosts=settings.allowed_generator_provider_hosts,
            timeout_seconds=settings.generator_timeout_seconds,
        )
    raise ProviderFailure("provider_not_configured", "generation provider is not configured")


def supports_generation_provider(provider_name: str, model_version: str) -> bool:
    """Return whether the runtime registry can instantiate this exact pair."""

    try:
        generation_provider(provider_name, model_version)
    except (ProviderFailure, ValueError):
        return False
    return True
