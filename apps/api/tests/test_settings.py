from edu_grader_api.settings import Settings


def test_settings_exposes_required_oidc_configuration() -> None:
    settings = Settings(
        oidc_issuer="http://keycloak:8080/realms/edu-grader",
        oidc_audience="edu-grader-api",
        bootstrap_admin_sub="admin-subject",
        bootstrap_admin_tenant_slug="pilot",
    )

    assert settings.oidc_school_id_claim == "school_id"
