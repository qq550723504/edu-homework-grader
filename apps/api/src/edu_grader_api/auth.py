from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property, lru_cache
import json
from typing import Annotated, Protocol
from urllib.error import URLError
from urllib.request import urlopen

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import append_audit_event
from .db import get_session
from .models import Role, Tenant, User
from .settings import settings


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    school_id: str | None


@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: str
    tenant_id: str
    role: Role
    school_id: str | None
    display_name: str
    oidc_subject: str = ""


class TokenVerifier(Protocol):
    def verify(self, token: str) -> VerifiedIdentity: ...


class PyJWKTokenVerifier:
    """Verify access tokens with the configured OIDC issuer's published JWKS."""

    def __init__(self, issuer: str, audience: str, school_id_claim: str) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.school_id_claim = school_id_claim

    @cached_property
    def jwk_client(self) -> PyJWKClient:
        discovery_url = f"{self.issuer}/.well-known/openid-configuration"
        try:
            with urlopen(discovery_url, timeout=5) as response:  # noqa: S310
                discovery = json.load(response)
            jwks_uri = discovery["jwks_uri"]
        except (KeyError, OSError, URLError, json.JSONDecodeError) as error:
            raise InvalidTokenError("unable to load OIDC discovery metadata") from error

        if not isinstance(jwks_uri, str):
            raise InvalidTokenError("OIDC discovery metadata has an invalid JWKS URI")
        return PyJWKClient(jwks_uri)

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise InvalidTokenError("unsupported token algorithm")
            signing_key = self.jwk_client.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
        except (InvalidTokenError, PyJWKClientError, ValueError) as error:
            raise InvalidTokenError("invalid access token") from error

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise InvalidTokenError("access token has no subject")

        school_id = claims.get(self.school_id_claim)
        if school_id is not None and not isinstance(school_id, str):
            raise InvalidTokenError("access token school identifier is invalid")

        return VerifiedIdentity(issuer=claims["iss"], subject=subject, school_id=school_id)


@lru_cache
def get_token_verifier() -> TokenVerifier:
    return PyJWKTokenVerifier(
        issuer=settings.oidc_issuer,
        audience=settings.oidc_audience,
        school_id_claim=settings.oidc_school_id_claim,
    )


security = HTTPBearer(auto_error=False)


def unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    session: Annotated[Session, Depends(get_session)],
    verifier: Annotated[TokenVerifier, Depends(get_token_verifier)],
) -> CurrentPrincipal:
    if credentials is None:
        raise unauthorized()

    try:
        identity = verifier.verify(credentials.credentials)
    except (InvalidTokenError, ValueError):
        raise unauthorized() from None

    if identity.issuer != settings.oidc_issuer or not identity.subject:
        raise unauthorized()

    user = session.scalar(
        select(User).where(
            User.oidc_issuer == identity.issuer,
            User.oidc_subject == identity.subject,
        )
    )
    if user is None:
        user = bind_rostered_student(session, identity)

    if user is None:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == settings.oidc_tenant_slug))
        if tenant is not None:
            append_audit_event(
                session,
                tenant_id=tenant.id,
                actor_user_id=None,
                event_type="auth.login_denied",
                target_type="tenant",
                target_id=tenant.id,
                metadata={"reason": "platform_membership_required"},
            )
            session.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="platform membership required"
        )
    if user.tenant.slug != settings.oidc_tenant_slug:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="resource not found")

    return CurrentPrincipal(
        user_id=str(user.id),
        tenant_id=str(user.tenant_id),
        role=user.role,
        school_id=user.school_id,
        display_name=user.display_name,
        oidc_subject=user.oidc_subject or "",
    )


def bind_rostered_student(session: Session, identity: VerifiedIdentity) -> User | None:
    """Bind one verified identity to a pre-imported student in the trusted tenant."""
    if not identity.school_id:
        return None

    tenant = session.scalar(select(Tenant).where(Tenant.slug == settings.oidc_tenant_slug))
    if tenant is None:
        return None

    user = session.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.role == Role.STUDENT,
            User.school_id == identity.school_id,
            User.oidc_subject.is_(None),
        )
    )
    if user is None:
        return None

    user.oidc_issuer = identity.issuer
    user.oidc_subject = identity.subject
    append_audit_event(
        session,
        tenant_id=user.tenant_id,
        actor_user_id=user.id,
        event_type="auth.login_succeeded",
        target_type="user",
        target_id=user.id,
        metadata={"binding_created": True},
    )
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return None
    return user
