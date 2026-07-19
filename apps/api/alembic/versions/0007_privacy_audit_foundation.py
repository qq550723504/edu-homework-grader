"""Add tamper-evident audit ledger fields and PostgreSQL append protection."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_privacy_audit_foundation"
down_revision: Union[str, Sequence[str], None] = "0006_student_appeals_and_corrections"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_chain_heads",
        sa.Column("tenant_id", sa.Uuid(), primary_key=True),
        sa.Column("next_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("latest_entry_hash", sa.String(64), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
    )
    with op.batch_alter_table("audit_logs") as batch:
        batch.add_column(sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("previous_hash", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("entry_hash", sa.String(64), nullable=False, server_default=""))
        batch.add_column(sa.Column("signature", sa.String(64), nullable=False, server_default=""))
        batch.add_column(
            sa.Column("key_version", sa.String(50), nullable=False, server_default="legacy-unsigned")
        )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_audit_log_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'audit_logs are append-only';
            END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER audit_logs_no_update_or_delete
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_log_mutation();
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update_or_delete ON audit_logs")
        op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_mutation()")
    with op.batch_alter_table("audit_logs") as batch:
        batch.drop_column("key_version")
        batch.drop_column("signature")
        batch.drop_column("entry_hash")
        batch.drop_column("previous_hash")
        batch.drop_column("sequence")
    op.drop_table("audit_chain_heads")
