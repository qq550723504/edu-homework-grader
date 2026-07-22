"""Reserve generation quota with one tenant-day counter row."""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0022_generation_quota_usages"
down_revision: Union[str, Sequence[str], None] = "0021_protect_ai_review_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_quota_usages",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("quota_day", sa.Date(), nullable=False),
        sa.Column("used_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "quota_day"),
    )
    op.create_table(
        "generation_quota_reservations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("quota_day", sa.Date(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "idempotency_key"),
    )


def downgrade() -> None:
    op.drop_table("generation_quota_reservations")
    op.drop_table("generation_quota_usages")
