"""Create governance control entries for AI candidate generation."""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0024_generation_governance_entries"
down_revision: Union[str, Sequence[str], None] = "0023_generation_batch_acceptances"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


governance_control_state_enum = sa.Enum(
    "active",
    "canary",
    "paused",
    "retired",
    name="generation_control_state",
    native_enum=False,
)
governance_target_type_enum = sa.Enum(
    "generator",
    "curriculum_profile",
    "prompt_version",
    "provider",
    "model",
    name="generation_governance_target_type",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "generation_governance_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=False, default=False),
        sa.Column(
            "target_type",
            governance_target_type_enum,
            nullable=False,
        ),
        sa.Column("target_key", sa.String(length=255), nullable=False),
        sa.Column(
            "control_state",
            governance_control_state_enum,
            nullable=False,
        ),
        sa.Column("note", sa.String(length=1_000), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(is_global = true AND tenant_id IS NULL) OR "
            "(is_global = false AND tenant_id IS NOT NULL)",
            name="ck_generation_governance_scope_is_consistent",
        ),
    )
    op.create_index(
        "uq_generation_governance_global_target",
        "generation_governance_entries",
        ["target_type", "target_key"],
        unique=True,
        postgresql_where=sa.text("is_global"),
        sqlite_where=sa.text("is_global = 1"),
    )
    op.create_index(
        "uq_generation_governance_tenant_target",
        "generation_governance_entries",
        ["tenant_id", "target_type", "target_key"],
        unique=True,
        postgresql_where=sa.text("NOT is_global"),
        sqlite_where=sa.text("is_global = 0"),
    )


def downgrade() -> None:
    op.drop_table("generation_governance_entries")
