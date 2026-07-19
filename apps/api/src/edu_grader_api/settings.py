from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader"
    redis_url: str = "redis://localhost:6379/0"
    grader_base_url: str = "http://localhost:8010"
    oidc_issuer: str = "http://localhost:8080/realms/edu-grader"
    oidc_audience: str = "edu-grader-api"
    oidc_school_id_claim: str = "school_id"
    oidc_tenant_slug: str = "pilot"
    bootstrap_admin_sub: str = ""
    bootstrap_admin_tenant_slug: str = ""
    audit_hmac_key: str = "development-only-change-me-32-bytes-minimum"
    audit_hmac_key_version: str = "dev-1"
    processor_allowed_hosts: str = "grader,languagetool,localhost"

    @model_validator(mode="after")
    def require_production_security_controls(self) -> "Settings":
        if self.app_env == "production":
            if len(self.audit_hmac_key.encode("utf-8")) < 32:
                raise ValueError("AUDIT_HMAC_KEY must be at least 32 bytes in production")
            if not self.allowed_processor_hosts:
                raise ValueError("PROCESSOR_ALLOWED_HOSTS is required in production")
        return self

    @property
    def allowed_processor_hosts(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold()
            for item in self.processor_allowed_hosts.split(",")
            if item.strip()
        )


settings = Settings()
