from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.exceptions import InvalidTokenError

from edu_grader_api.github_oidc import GitHubOidcTrust, GitHubOidcVerifier


PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TRUST = GitHubOidcTrust(
    audience="https://edu.getkr.com/operational-evaluation",
    repository_id="123",
    repository_owner_id="456",
    workflow_ref=(
        "qq550723504/edu-homework-grader/"
        ".github/workflows/ai-evaluation-operational.yml@refs/heads/main"
    ),
)


class StaticJwkClient:
    def get_signing_key_from_jwt(self, _token: str) -> SimpleNamespace:
        return SimpleNamespace(key=PRIVATE_KEY.public_key())


def protected_claims() -> dict[str, object]:
    return {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": TRUST.audience,
        "sub": "repo:qq550723504/edu-homework-grader:environment:ai-evaluation-operational",
        "repository": "qq550723504/edu-homework-grader",
        "repository_id": TRUST.repository_id,
        "repository_owner_id": TRUST.repository_owner_id,
        "repository_visibility": "public",
        "ref": "refs/heads/main",
        "ref_type": "branch",
        "event_name": "workflow_dispatch",
        "environment": "ai-evaluation-operational",
        "workflow_ref": TRUST.workflow_ref,
        "runner_environment": "github-hosted",
        "run_id": "789",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }


def signed_token(**overrides: object) -> str:
    claims = protected_claims() | overrides
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256")


def verifier(monkeypatch: pytest.MonkeyPatch) -> GitHubOidcVerifier:
    instance = GitHubOidcVerifier(TRUST)
    monkeypatch.setattr(instance, "jwk_client", StaticJwkClient())
    return instance


def test_verifier_accepts_only_the_protected_main_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = verifier(monkeypatch).verify(signed_token())

    assert identity.repository_id == "123"
    assert identity.owner_id == "456"
    assert identity.run_id == "789"
    assert identity.workflow_ref == TRUST.workflow_ref


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("repository_id", "wrong-repository"),
        ("repository_owner_id", "wrong-owner"),
        ("repository_visibility", "private"),
        ("ref", "refs/heads/feature"),
        ("event_name", "push"),
        ("environment", "production"),
        (
            "workflow_ref",
            "qq550723504/edu-homework-grader/.github/workflows/ci.yml@refs/heads/main",
        ),
        ("runner_environment", "self-hosted"),
    ],
)
def test_verifier_rejects_a_wrong_trust_claim(
    monkeypatch: pytest.MonkeyPatch, claim: str, value: str
) -> None:
    with pytest.raises(InvalidTokenError, match="GitHub workflow is not trusted"):
        verifier(monkeypatch).verify(signed_token(**{claim: value}))


def test_verifier_rejects_a_wrong_audience(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(InvalidTokenError, match="invalid GitHub OIDC token"):
        verifier(monkeypatch).verify(signed_token(aud="https://example.invalid"))
