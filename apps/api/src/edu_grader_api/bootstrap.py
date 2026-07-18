from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import Role, Tenant, User
from .settings import settings


def bootstrap_admin(session: Session, *, issuer: str, subject: str, tenant_slug: str) -> User:
    """Create the configured pilot administrator once without altering another identity."""
    if not issuer or not subject or not tenant_slug:
        raise ValueError("issuer, subject, and tenant_slug are required")

    existing = session.scalar(
        select(User).where(User.oidc_issuer == issuer, User.oidc_subject == subject)
    )
    if existing is not None:
        if existing.role is not Role.ADMIN or existing.tenant.slug != tenant_slug:
            raise ValueError("configured OIDC identity already belongs to another user")
        return existing

    tenant = session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
    if tenant is None:
        tenant = Tenant(slug=tenant_slug, name=tenant_slug)
        session.add(tenant)
        session.flush()

    admin = User(
        tenant=tenant,
        role=Role.ADMIN,
        oidc_issuer=issuer,
        oidc_subject=subject,
        display_name="Pilot administrator",
    )
    session.add(admin)
    session.flush()
    return admin


def main() -> None:
    """Run the explicit deployment-time bootstrap command."""
    with SessionLocal.begin() as session:
        bootstrap_admin(
            session,
            issuer=settings.oidc_issuer,
            subject=settings.bootstrap_admin_sub,
            tenant_slug=settings.bootstrap_admin_tenant_slug,
        )


if __name__ == "__main__":
    main()
