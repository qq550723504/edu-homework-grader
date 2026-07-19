import json
from pathlib import Path

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
    realm = json.loads(
        Path("infra/keycloak/edu-grader-realm.json").read_text(encoding="utf-8")
    )
    web_client = next(client for client in realm["clients"] if client["clientId"] == "edu-grader-web")

    assert "email" not in web_client["defaultClientScopes"]
    assert "profile" not in web_client["defaultClientScopes"]
    assert "school-id" in web_client["defaultClientScopes"]
