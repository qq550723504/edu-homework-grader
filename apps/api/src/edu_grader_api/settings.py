from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_AUDIT_HMAC_KEY = "development-only-change-me-32-bytes-minimum"
PRODUCTION_PROCESSOR_HOSTS: frozenset[str] = frozenset({"grader", "languagetool"})


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
    curriculum_admin_subjects: str = ""
    audit_hmac_key: str = DEFAULT_AUDIT_HMAC_KEY
    audit_hmac_key_version: str = "dev-1"
    processor_allowed_hosts: str = "grader,languagetool,localhost"

    @model_validator(mode="after")
    def require_production_security_controls(self) -> "Settings":
        if self.app_env == "production":
            if self.audit_hmac_key == DEFAULT_AUDIT_HMAC_KEY:
                raise ValueError(
                    "AUDIT_HMAC_KEY must not use the development default in production"
                )
            if len(self.audit_hmac_key.encode("utf-8")) < 32:
                raise ValueError("AUDIT_HMAC_KEY must be at least 32 bytes in production")
            if "change-me" in self.database_url:
                raise ValueError("DATABASE_URL must not use a development password in production")
            issuer = urlparse(self.oidc_issuer)
            if issuer.scheme != "https" or issuer.hostname in {None, "localhost", "127.0.0.1"}:
                raise ValueError("OIDC_ISSUER must use a non-local HTTPS issuer in production")
            if not self.allowed_processor_hosts:
                raise ValueError("PROCESSOR_ALLOWED_HOSTS is required in production")
            if any("*" in host for host in self.allowed_processor_hosts):
                raise ValueError("PROCESSOR_ALLOWED_HOSTS must not contain wildcards in production")
            if not self.allowed_processor_hosts.issubset(PRODUCTION_PROCESSOR_HOSTS):
                raise ValueError(
                    "PROCESSOR_ALLOWED_HOSTS contains hosts not approved for production"
                )
            grader_host = urlparse(self.grader_base_url).hostname
            if grader_host not in self.allowed_processor_hosts:
                raise ValueError(
                    "GRADER_BASE_URL must use a host in PROCESSOR_ALLOWED_HOSTS in production"
                )
        return self

    @property
    def allowed_processor_hosts(self) -> frozenset[str]:
        return frozenset(
            item.strip().casefold()
            for item in self.processor_allowed_hosts.split(",")
            if item.strip()
        )

    @property
    def curriculum_admin_subject_set(self) -> frozenset[str]:
        return frozenset(
            item.strip() for item in self.curriculum_admin_subjects.split(",") if item.strip()
        )


settings = Settings()
