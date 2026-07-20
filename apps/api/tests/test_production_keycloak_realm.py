import json
from pathlib import Path


REALM_PATH = Path(__file__).resolve().parents[3] / "infra" / "k8s" / "production" / "realm.json"


def test_production_realm_has_only_https_public_callback_and_no_demo_users() -> None:
    realm_text = REALM_PATH.read_text(encoding="utf-8")
    realm = json.loads(realm_text)
    client = next(item for item in realm["clients"] if item["clientId"] == "edu-grader-web")

    assert realm.get("users", []) == []
    assert client["redirectUris"] == ["https://edu.getkr.com/*"]
    assert client["webOrigins"] == ["https://edu.getkr.com"]
    assert client["directAccessGrantsEnabled"] is False
    assert "pilot-admin" not in realm_text
    assert "pilot-teacher" not in realm_text
    assert "pilot-student" not in realm_text
