import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

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
    assert "offline_access" in web_client["defaultClientScopes"]
    assert "edu-grader-subject" in web_client["defaultClientScopes"]
    assert {
        "http://localhost:3000/*",
        "http://localhost:13000/*",
    }.issubset(web_client["redirectUris"])

    subject_scope = next(
        scope for scope in realm["clientScopes"] if scope["name"] == "edu-grader-subject"
    )
    assert subject_scope["protocolMappers"] == [
        {
            "name": "subject",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-sub-mapper",
            "consentRequired": False,
            "config": {
                "access.token.claim": "true",
                "id.token.claim": "true",
                "userinfo.token.claim": "true",
                "introspection.token.claim": "true",
            },
        }
    ]


def test_development_realm_users_do_not_require_profile_completion() -> None:
    realm = json.loads(Path("infra/keycloak/edu-grader-realm.json").read_text(encoding="utf-8"))
    users = {user["username"]: user for user in realm["users"]}

    for username in ("pilot-admin", "pilot-teacher", "pilot-student"):
        user = users[username]
        assert user["email"].endswith("@example.invalid")
        assert user["emailVerified"] is True
        assert user["firstName"]
        assert user["lastName"]
        assert "offline_access" in user["realmRoles"]


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


@pytest.mark.parametrize("processor_allowed_hosts", ["grader,external.example", "localhost"])
def test_production_settings_reject_unreviewed_processor_hosts(
    processor_allowed_hosts: str,
) -> None:
    with pytest.raises(ValueError, match="PROCESSOR_ALLOWED_HOSTS"):
        Settings(
            app_env="production",
            audit_hmac_key="x" * 32,
            database_url="postgresql://edu_grader:secure-password@db.example/edu_grader",
            oidc_issuer="https://identity.example/realms/edu-grader",
            processor_allowed_hosts=processor_allowed_hosts,
        )


def test_development_settings_allow_localhost_processor_host() -> None:
    settings = Settings(processor_allowed_hosts="grader,localhost")

    assert settings.allowed_processor_hosts == {"grader", "localhost"}


def test_openai_provider_default_uses_the_versioned_api_endpoint() -> None:
    settings = Settings()

    assert settings.generator_openai_base_url == "https://api.openai.com/v1"


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5-2025-08-07",
        "gpt-4-0613",
        "gpt-3.5-turbo-0125",
        "ft:gpt-4o-mini:acemeco:suffix:abc123",
    ],
)
def test_production_openai_settings_accept_an_immutable_model_id(model: str) -> None:
    settings = Settings(
        app_env="production",
        audit_hmac_key="x" * 32,
        database_url="postgresql://edu_grader:secure-password@db.example/edu_grader",
        oidc_issuer="https://identity.example/realms/edu-grader",
        processor_allowed_hosts="grader",
        grader_base_url="http://grader:8010",
        generation_provider="openai",
        openai_api_key="test-key",
        generator_openai_model=model,
        generator_provider_allowed_hosts="api.openai.com",
    )

    assert settings.generator_openai_model == model


def test_production_openai_settings_require_an_explicit_model() -> None:
    with pytest.raises(ValueError, match="GENERATOR_OPENAI_MODEL is required"):
        Settings(
            app_env="production",
            audit_hmac_key="x" * 32,
            database_url="postgresql://edu_grader:secure-password@db.example/edu_grader",
            oidc_issuer="https://identity.example/realms/edu-grader",
            processor_allowed_hosts="grader",
            grader_base_url="http://grader:8010",
            generation_provider="openai",
            openai_api_key="test-key",
            generator_provider_allowed_hosts="api.openai.com",
        )


@pytest.mark.parametrize(
    "model",
    [
        "gpt-5",
        "latest",
        "gpt-5-2025-02-30",
        "gpt-4-0230",
        "gpt-4-1332",
        "ft:gpt-4o-mini:acemeco:suffix",
        "ft:gpt-4o-mini:acemeco::abc123",
        " -2025-08-07",
        "gpt\u200b-2025-08-07",
        "gpt-5-2025-08-07 ",
        "gpt-5-2025-08-07\n",
    ],
)
def test_production_openai_settings_reject_unpinned_model_without_echoing_it(model: str) -> None:
    with pytest.raises(ValueError, match="OpenAI model must use an immutable model ID") as error:
        Settings(
            app_env="production",
            audit_hmac_key="x" * 32,
            database_url="postgresql://edu_grader:secure-password@db.example/edu_grader",
            oidc_issuer="https://identity.example/realms/edu-grader",
            processor_allowed_hosts="grader",
            grader_base_url="http://grader:8010",
            generation_provider="openai",
            openai_api_key="secret-key-that-must-not-appear",
            generator_openai_model=model,
            generator_provider_allowed_hosts="api.openai.com",
        )

    assert model not in str(error.value)
    assert "secret-key-that-must-not-appear" not in str(error.value)


@pytest.mark.parametrize(
    "entrypoint", ["constructor", "mapping", "json", "strings", "type_adapter"]
)
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("generator_openai_model", "gpt-5", "OpenAI model must use an immutable model ID"),
        ("grader_base_url", "http://external.example:8010", "GRADER_BASE_URL"),
    ],
)
def test_production_security_errors_do_not_wrap_settings_input(
    entrypoint: str, field: str, value: str, message: str
) -> None:
    secret = "secret-key-that-must-not-appear"
    options = {
        "app_env": "production",
        "audit_hmac_key": "x" * 32,
        "database_url": "postgresql://edu_grader:secure-password@db.example/edu_grader",
        "oidc_issuer": "https://identity.example/realms/edu-grader",
        "processor_allowed_hosts": "grader",
        "grader_base_url": "http://grader:8010",
        "generation_provider": "openai",
        "openai_api_key": secret,
        "generator_openai_model": "gpt-5-2025-08-07",
        "generator_provider_allowed_hosts": "api.openai.com",
    }
    options[field] = value

    with pytest.raises(ValueError, match=message) as error:
        if entrypoint == "constructor":
            Settings(**options)
        elif entrypoint == "mapping":
            Settings.model_validate(options)
        elif entrypoint == "strings":
            Settings.model_validate_strings(options)
        elif entrypoint == "type_adapter":
            TypeAdapter(Settings).validate_python(options)
        else:
            Settings.model_validate_json(json.dumps(options))

    assert secret not in str(error.value)
    assert secret not in repr(error.value)
    if hasattr(error.value, "errors"):
        errors = error.value.errors()
        assert errors[0]["loc"] == ("ai_duplicate_similarity_threshold",)
        assert errors[0]["input"] == 0.92
        assert secret not in repr(errors)
        assert secret not in error.value.json()


@pytest.mark.parametrize(
    "entrypoint", ["constructor", "mapping", "json", "strings", "type_adapter"]
)
def test_invalid_threshold_prevents_production_security_cross_field_validation(
    entrypoint: str,
) -> None:
    secret = "secret-key-that-must-not-appear"
    options = {
        "app_env": "production",
        "audit_hmac_key": "x" * 32,
        "database_url": "postgresql://edu_grader:secure-password@db.example/edu_grader",
        "oidc_issuer": "https://identity.example/realms/edu-grader",
        "processor_allowed_hosts": "grader",
        "grader_base_url": "http://grader:8010",
        "generation_provider": "openai",
        "openai_api_key": secret,
        "generator_openai_model": "gpt-5",
        "generator_provider_allowed_hosts": "api.openai.com",
        "ai_duplicate_similarity_threshold": "not-a-number",
    }

    with pytest.raises(ValueError) as error:
        if entrypoint == "constructor":
            Settings(**options)
        elif entrypoint == "mapping":
            Settings.model_validate(options)
        elif entrypoint == "strings":
            Settings.model_validate_strings(options)
        elif entrypoint == "type_adapter":
            TypeAdapter(Settings).validate_python(options)
        else:
            Settings.model_validate_json(json.dumps(options))

    assert "immutable model" not in str(error.value)
    assert secret not in str(error.value)
    assert secret not in repr(error.value)
    errors = error.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("ai_duplicate_similarity_threshold",)
    assert errors[0]["input"] == "not-a-number"
    assert secret not in repr(errors)
    assert secret not in error.value.json()


def test_ai_duplicate_similarity_threshold_defaults_to_conservative_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_DUPLICATE_SIMILARITY_THRESHOLD", raising=False)

    settings = Settings(_env_file=None)

    assert settings.ai_duplicate_similarity_threshold == 0.92


def test_ai_duplicate_similarity_threshold_uses_environment_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_DUPLICATE_SIMILARITY_THRESHOLD", "0.87")

    settings = Settings(_env_file=None)

    assert settings.ai_duplicate_similarity_threshold == 0.87


@pytest.mark.parametrize("threshold", [-0.01, 1.01, float("nan")])
def test_ai_duplicate_similarity_threshold_rejects_invalid_values(threshold: float) -> None:
    with pytest.raises(ValueError):
        Settings(ai_duplicate_similarity_threshold=threshold)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("database_url", "postgresql://edu_grader:change-me@db/edu_grader", "DATABASE_URL"),
        ("oidc_issuer", "http://localhost:8080/realms/edu-grader", "OIDC_ISSUER"),
        ("processor_allowed_hosts", "grader,*", "PROCESSOR_ALLOWED_HOSTS"),
        ("grader_base_url", "http://external.example:8010", "GRADER_BASE_URL"),
        ("grader_base_url", "http://localhost:8010", "GRADER_BASE_URL"),
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
