import json
from pathlib import Path


REALM_PATH = (
    Path(__file__).resolve().parents[3]
    / "infra"
    / "k8s"
    / "production"
    / "realm.json"
)


def test_production_realm_has_only_https_public_callback_and_no_demo_users() -> None:
    realm = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    client = next(item for item in realm["clients"] if item["clientId"] == "edu-grader-web")

    assert realm.get("users", []) == []
    assert client["redirectUris"] == ["https://edu.getkr.com/*"]
    assert client["webOrigins"] == ["https://edu.getkr.com"]
    assert client["directAccessGrantsEnabled"] is False
