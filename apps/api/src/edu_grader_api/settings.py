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


settings = Settings()
