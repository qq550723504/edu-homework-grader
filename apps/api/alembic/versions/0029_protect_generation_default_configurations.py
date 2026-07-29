"""Make governed default configuration identities immutable.

Revision ID: 0029_protect_generation_default_configurations
Revises: 0028_generation_default_governance_hardening
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0029_protect_generation_default_configurations"
down_revision: str | Sequence[str] | None = "0028_generation_default_governance_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _install_generation_default_configuration_protection_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE FUNCTION prevent_generation_default_configuration_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'generation default configuration is immutable';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER generation_default_configurations_no_update_or_delete
        BEFORE UPDATE OR DELETE ON generation_default_configurations
        FOR EACH ROW
        EXECUTE FUNCTION prevent_generation_default_configuration_mutation();
        """
    )


def _remove_generation_default_configuration_protection_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        DROP TRIGGER IF EXISTS generation_default_configurations_no_update_or_delete
        ON generation_default_configurations;
        DROP FUNCTION IF EXISTS prevent_generation_default_configuration_mutation();
        """
    )


def upgrade() -> None:
    _install_generation_default_configuration_protection_triggers()


def downgrade() -> None:
    _remove_generation_default_configuration_protection_triggers()
