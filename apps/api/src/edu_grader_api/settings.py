from urllib.parse import urlparse

from edu_generator.model_snapshots import validate_immutable_openai_model_id
from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AUDIT_HMAC_KEY = "development-only-change-me-32-bytes-minimum"
PRODUCTION_PROCESSOR_HOSTS: frozenset[str] = frozenset({"grader", "languagetool"})


def _parse_allowed_hosts(hosts: str) -> frozenset[str]:
    return frozenset(item.strip().casefold() for item in hosts.split(",") if item.strip())


def _parse_subjects(subjects: str) -> frozenset[str]:
    return frozenset(item.strip() for item in subjects.split(",") if item.strip())


def _require_production_security_controls(
    *,
    app_env: str,
    audit_hmac_key: str,
    database_url: str,
    oidc_issuer: str,
    processor_allowed_hosts: str,
    grader_base_url: str,
    generation_provider: str,
    openai_api_key: str,
    generator_openai_model: str,
    generator_provider_allowed_hosts: str,
) -> None:
    if app_env != "production":
        return

    if audit_hmac_key == DEFAULT_AUDIT_HMAC_KEY:
        raise ValueError("AUDIT_HMAC_KEY must not use the development default in production")
    if len(audit_hmac_key.encode("utf-8")) < 32:
        raise ValueError("AUDIT_HMAC_KEY must be at least 32 bytes in production")
    if "change-me" in database_url:
        raise ValueError("DATABASE_URL must not use a development password in production")
    issuer = urlparse(oidc_issuer)
    if issuer.scheme != "https" or issuer.hostname in {None, "localhost", "127.0.0.1"}:
        raise ValueError("OIDC_ISSUER must use a non-local HTTPS issuer in production")
    allowed_processor_hosts = _parse_allowed_hosts(processor_allowed_hosts)
    if not allowed_processor_hosts:
        raise ValueError("PROCESSOR_ALLOWED_HOSTS is required in production")
    if any("*" in host for host in allowed_processor_hosts):
        raise ValueError("PROCESSOR_ALLOWED_HOSTS must not contain wildcards in production")
    if not allowed_processor_hosts.issubset(PRODUCTION_PROCESSOR_HOSTS):
        raise ValueError("PROCESSOR_ALLOWED_HOSTS contains hosts not approved for production")
    grader_host = urlparse(grader_base_url).hostname
    if grader_host not in allowed_processor_hosts:
        raise ValueError("GRADER_BASE_URL must use a host in PROCESSOR_ALLOWED_HOSTS in production")
    if generation_provider != "openai":
        return

    if not openai_api_key:
        raise ValueError("OPENAI_API_KEY is required when GENERATION_PROVIDER=openai")
    if not generator_openai_model:
        raise ValueError("GENERATOR_OPENAI_MODEL is required when GENERATION_PROVIDER=openai")
    validate_immutable_openai_model_id(generator_openai_model)
    if not generator_provider_allowed_hosts:
        raise ValueError("GENERATOR_PROVIDER_ALLOWED_HOSTS is required")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", populate_by_name=True, validate_default=True
    )

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader"
    redis_url: str = "redis://localhost:6379/0"
    grader_base_url: str = "http://localhost:8010"
    grader_request_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=60,
        validation_alias="GRADER_REQUEST_TIMEOUT_SECONDS",
    )
    verification_total_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=120,
        validation_alias="VERIFICATION_TOTAL_TIMEOUT_SECONDS",
    )
    oidc_issuer: str = "http://localhost:8080/realms/edu-grader"
    oidc_audience: str = "edu-grader-api"
    oidc_school_id_claim: str = "school_id"
    oidc_tenant_slug: str = "pilot"
    bootstrap_admin_sub: str = ""
    bootstrap_admin_tenant_slug: str = ""
    curriculum_admin_subjects: str = ""
    generation_governance_admin_subjects: str = ""
    audit_hmac_key: str = DEFAULT_AUDIT_HMAC_KEY
    audit_hmac_key_version: str = "dev-1"
    processor_allowed_hosts: str = "grader,languagetool,localhost"
    generation_provider: str = "fake"
    openai_api_key: str = ""
    generator_openai_model: str = ""
    generator_openai_base_url: str = "https://api.openai.com/v1"
    generator_provider_allowed_hosts: str = "api.openai.com"
    generator_timeout_seconds: float = 30
    generator_daily_tenant_limit: int = 100
    generator_max_batch_size: int = 20
    ai_duplicate_similarity_threshold: float = Field(
        default=0.92,
        ge=0,
        le=1,
        validation_alias="AI_DUPLICATE_SIMILARITY_THRESHOLD",
    )

    @field_validator("ai_duplicate_similarity_threshold", mode="after")
    @classmethod
    def require_production_security_controls(
        cls, ai_duplicate_similarity_threshold: float, info: ValidationInfo
    ) -> float:
        required_fields = (
            "app_env",
            "audit_hmac_key",
            "database_url",
            "oidc_issuer",
            "processor_allowed_hosts",
            "grader_base_url",
            "generation_provider",
            "openai_api_key",
            "generator_openai_model",
            "generator_provider_allowed_hosts",
        )
        if any(field not in info.data for field in required_fields):
            return ai_duplicate_similarity_threshold

        _require_production_security_controls(
            app_env=info.data["app_env"],
            audit_hmac_key=info.data["audit_hmac_key"],
            database_url=info.data["database_url"],
            oidc_issuer=info.data["oidc_issuer"],
            processor_allowed_hosts=info.data["processor_allowed_hosts"],
            grader_base_url=info.data["grader_base_url"],
            generation_provider=info.data["generation_provider"],
            openai_api_key=info.data["openai_api_key"],
            generator_openai_model=info.data["generator_openai_model"],
            generator_provider_allowed_hosts=info.data["generator_provider_allowed_hosts"],
        )
        return ai_duplicate_similarity_threshold

    @property
    def allowed_processor_hosts(self) -> frozenset[str]:
        return _parse_allowed_hosts(self.processor_allowed_hosts)

    @property
    def curriculum_admin_subject_set(self) -> frozenset[str]:
        return _parse_subjects(self.curriculum_admin_subjects)

    @property
    def generation_governance_admin_subject_set(self) -> frozenset[str]:
        return _parse_subjects(self.generation_governance_admin_subjects)

    @property
    def allowed_generator_provider_hosts(self) -> frozenset[str]:
        return _parse_allowed_hosts(self.generator_provider_allowed_hosts)


settings = Settings()
