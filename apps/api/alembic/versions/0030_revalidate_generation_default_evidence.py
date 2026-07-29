"""Persist signed default-governance evidence for application-time verification.

Revision ID: 0030_revalidate_generation_default_evidence
Revises: 0029_protect_generation_default_configurations
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_revalidate_generation_default_evidence"
down_revision: str | Sequence[str] | None = "0029_protect_generation_default_configurations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_default_change_requests",
        sa.Column("evaluation_evidence_json", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("generation_default_change_requests", "evaluation_evidence_json")
