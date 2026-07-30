from __future__ import annotations

import secrets
from urllib.parse import quote

import httpx


class KeycloakAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        client_id: str,
        client_secret: str,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.client_id = client_id
        self.client_secret = client_secret
        self.client = client or httpx.Client(timeout=10)

    def ensure_student(self, *, school_id: str, display_name: str, activation_code: str) -> str:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        username = school_id.lower()
        users = self.client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users",
            params={"username": username, "exact": "true"},
            headers=headers,
        )
        users.raise_for_status()
        if users.json():
            user_id = users.json()[0]["id"]
        else:
            created = self.client.post(
                f"{self.base_url}/admin/realms/{self.realm}/users",
                json={
                    "username": username,
                    "enabled": True,
                    "attributes": {"school_id": [school_id]},
                },
                headers=headers,
            )
            created.raise_for_status()
            user_id = created.headers["Location"].rstrip("/").rsplit("/", 1)[1]
        existing = self.client.get(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}", headers=headers
        )
        existing.raise_for_status()
        existing_attributes = existing.json().get("attributes")
        attributes = existing_attributes if isinstance(existing_attributes, dict) else {}
        attributes["school_id"] = [school_id]
        self.client.put(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}",
            json={"attributes": attributes},
            headers=headers,
        ).raise_for_status()
        role = self.client.get(
            f"{self.base_url}/admin/realms/{self.realm}/roles/{quote('student', safe='')}",
            headers=headers,
        )
        role.raise_for_status()
        self.client.post(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm",
            json=[role.json()],
            headers=headers,
        ).raise_for_status()
        self.client.put(
            f"{self.base_url}/admin/realms/{self.realm}/users/{user_id}/reset-password",
            json={"type": "password", "value": activation_code, "temporary": True},
            headers=headers,
        ).raise_for_status()
        return user_id

    def _access_token(self) -> str:
        response = self.client.post(
            f"{self.base_url}/realms/{self.realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])

    def disable_temporary_password(self, keycloak_user_id: str) -> None:
        headers = {"Authorization": f"Bearer {self._access_token()}"}
        self.client.put(
            f"{self.base_url}/admin/realms/{self.realm}/users/{keycloak_user_id}/reset-password",
            json={"type": "password", "value": secrets.token_urlsafe(32), "temporary": True},
            headers=headers,
        ).raise_for_status()
