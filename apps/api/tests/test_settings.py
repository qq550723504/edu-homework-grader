import json
from pathlib import Path

import pytest

from edu_grader_api.settings import Settings


def test_settings_exposes_required_oidc_configuration() -> None:
    settings = Settings(
        oidc_issuer="http://keycloak:8080/realms/edu-grader",
        oidc_audience="edu-grader-api",
        oidc_tenant_slug="pilot",
        bootstrap_admin_sub="admin-subject",
        bootstrap_admin_tenant_slug="pilot",
    )

    assert settings.oidc_school_id_claim == "school_id"
    assert settings.oidc_tenant_slug == "pilot"


def test_web_client_requests_no_email_or_profile_scope() -> None:
    realm = json.loads(Path("infra/keycloak/edu-grader-realm.json").read_text(encoding="utf-8"))
    web_client = next(
        client for client in realm["clients"] if client["clientId"] == "edu-grader-web"
    )

    assert "email" not in web_client["defaultClientScopes"]
    assert "profile" not in web_client["defaultClientScopes"]
    assert "school-id" in web_client["defaultClientScopes"]


def test_compose_requires_sensitive_development_values_instead_of_embedding_defaults() -> None:
    compose = Path("compose.yaml").read_text(encoding="utf-8")

    for variable in (
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "AUDIT_HMAC_KEY",
        "KEYCLOAK_ADMIN_USERNAME",
        "KEYCLOAK_ADMIN_PASSWORD",
        "KEYCLOAK_POSTGRES_PASSWORD",
    ):
        assert f"${{{variable}:?" in compose

    assert "change-me" not in compose
    assert "development-only-change-me" not in compose


@pytest.mark.parametrize(
    ("audit_hmac_key", "processor_allowed_hosts"),
    [("", "grader"), ("x" * 32, "")],
)
def test_production_settings_require_audit_key_and_processor_allowlist(
    audit_hmac_key: str, processor_allowed_hosts: str
) -> None:
    with pytest.raises(ValueError):
        Settings(
            app_env="production",
            audit_hmac_key=audit_hmac_key,
            processor_allowed_hosts=processor_allowed_hosts,
        )


def test_production_settings_reject_the_default_audit_key() -> None:
    with pytest.raises(ValueError, match="AUDIT_HMAC_KEY must not use the development default"):
        Settings(app_env="production", processor_allowed_hosts="grader")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("database_url", "postgresql://edu_grader:change-me@db/edu_grader", "DATABASE_URL"),
        ("oidc_issuer", "http://localhost:8080/realms/edu-grader", "OIDC_ISSUER"),
        ("processor_allowed_hosts", "grader,*", "PROCESSOR_ALLOWED_HOSTS"),
    ],
)
def test_production_settings_reject_insecure_dependency_configuration(
    field: str, value: str, message: str
) -> None:
    options = {
        "app_env": "production",
        "audit_hmac_key": "x" * 32,
        "database_url": "postgresql://edu_grader:secure-password@db.example/edu_grader",
        "oidc_issuer": "https://identity.example/realms/edu-grader",
        "processor_allowed_hosts": "grader",
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        Settings(**options)
