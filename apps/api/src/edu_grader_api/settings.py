from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://edu_grader:change-me@localhost:5432/edu_grader"
    redis_url: str = "redis://localhost:6379/0"
    grader_base_url: str = "http://localhost:8010"


settings = Settings()
