import json

import httpx


def test_keycloak_adapter_provisions_student_with_temporary_password() -> None:
    from edu_grader_api.services.keycloak_admin import KeycloakAdminClient

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/protocol/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "service-token"})
        if request.method == "GET" and request.url.path.endswith("/users"):
            return httpx.Response(200, json=[])
        if request.method == "POST" and request.url.path.endswith("/users"):
            return httpx.Response(
                201, headers={"Location": "http://keycloak:8080/admin/realms/edu-grader/users/kc-1"}
            )
        if request.method == "GET" and request.url.path.endswith("/users/kc-1"):
            return httpx.Response(200, json={"attributes": {"locale": ["zh-CN"]}})
        if request.url.path.endswith("/roles/student"):
            return httpx.Response(200, json={"id": "student-role", "name": "student"})
        return httpx.Response(204)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = KeycloakAdminClient(
            base_url="http://keycloak:8080",
            realm="edu-grader",
            client_id="student-provisioner",
            client_secret="service-secret",
            client=client,
        ).ensure_student(school_id="S-001", display_name="Ada", activation_code="activation-code")

    assert result == "kc-1"
    assert any(request.url.path.endswith("/role-mappings/realm") for request in requests)
    attribute_request = next(
        request
        for request in requests
        if request.method == "PUT" and request.url.path.endswith("/users/kc-1")
    )
    assert json.loads(attribute_request.content) == {
        "attributes": {"locale": ["zh-CN"], "school_id": ["S-001"]}
    }
    password_request = next(
        request for request in requests if request.url.path.endswith("/reset-password")
    )
    assert json.loads(password_request.content) == {
        "type": "password",
        "value": "activation-code",
        "temporary": True,
    }
