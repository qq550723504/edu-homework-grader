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
