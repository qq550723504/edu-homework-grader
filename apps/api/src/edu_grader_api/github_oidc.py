from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from .settings import Settings


GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_JWKS_URL = f"{GITHUB_OIDC_ISSUER}/.well-known/jwks"
OPERATIONAL_EVALUATION_ENVIRONMENT = "ai-evaluation-operational"


@dataclass(frozen=True)
class GitHubOidcTrust:
    audience: str
    repository_id: str
    repository_owner_id: str
    workflow_ref: str

    @classmethod
    def from_settings(cls, settings: Settings) -> GitHubOidcTrust:
        return cls(
            audience=settings.github_operational_evaluation_audience,
            repository_id=settings.github_operational_evaluation_repository_id,
            repository_owner_id=settings.github_operational_evaluation_owner_id,
            workflow_ref=settings.github_operational_evaluation_workflow_ref,
        )

    def require(self, claims: dict[str, object]) -> None:
        expected = {
            "repository_id": self.repository_id,
            "repository_owner_id": self.repository_owner_id,
            "repository_visibility": "public",
            "ref": "refs/heads/main",
            "ref_type": "branch",
            "event_name": "workflow_dispatch",
            "environment": OPERATIONAL_EVALUATION_ENVIRONMENT,
            "workflow_ref": self.workflow_ref,
            "runner_environment": "github-hosted",
        }
        if any(claims.get(key) != value for key, value in expected.items()):
            raise InvalidTokenError("GitHub workflow is not trusted")


@dataclass(frozen=True)
class GitHubWorkflowIdentity:
    repository_id: str
    owner_id: str
    run_id: str
    workflow_ref: str


class GitHubOidcVerifier:
    def __init__(self, trust: GitHubOidcTrust) -> None:
        self.trust = trust

    @cached_property
    def jwk_client(self) -> PyJWKClient:
        return PyJWKClient(GITHUB_OIDC_JWKS_URL)

    def verify(self, token: str) -> GitHubWorkflowIdentity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise InvalidTokenError("unsupported token algorithm")
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.trust.audience,
                issuer=GITHUB_OIDC_ISSUER,
                options={"require": ["exp", "repository_id", "repository_owner_id", "run_id"]},
            )
        except (InvalidTokenError, PyJWKClientError, ValueError) as error:
            raise InvalidTokenError("invalid GitHub OIDC token") from error

        self.trust.require(claims)
        run_id = claims["run_id"]
        if not isinstance(run_id, (str, int)) or not str(run_id):
            raise InvalidTokenError("GitHub workflow is not trusted")
        return GitHubWorkflowIdentity(
            repository_id=self.trust.repository_id,
            owner_id=self.trust.repository_owner_id,
            run_id=str(run_id),
            workflow_ref=self.trust.workflow_ref,
        )
