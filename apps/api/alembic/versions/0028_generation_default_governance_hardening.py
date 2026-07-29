"""Harden governed generation-default transitions.

Revision ID: 0028_generation_default_governance_hardening
Revises: 0027_generation_default_governance
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028_generation_default_governance_hardening"
down_revision: str | Sequence[str] | None = "0027_generation_default_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "generation_default_change_requests",
        sa.Column("evaluated_against_selection_request_id", sa.Uuid()),
    )
    op.create_foreign_key(
        "fk_generation_default_change_request_evaluated_selection",
        "generation_default_change_requests",
        "generation_default_change_requests",
        ["evaluated_against_selection_request_id"],
        ["id"],
    )
    op.add_column(
        "generation_default_change_requests", sa.Column("decision_idempotency_key", sa.String(128))
    )
    op.add_column(
        "generation_default_change_requests", sa.Column("decision_request_digest", sa.String(64))
    )
    op.add_column(
        "generation_default_change_requests",
        sa.Column("application_idempotency_key", sa.String(128)),
    )
    op.add_column(
        "generation_default_change_requests", sa.Column("application_request_digest", sa.String(64))
    )


def downgrade() -> None:
    op.drop_column("generation_default_change_requests", "application_request_digest")
    op.drop_column("generation_default_change_requests", "application_idempotency_key")
    op.drop_column("generation_default_change_requests", "decision_request_digest")
    op.drop_column("generation_default_change_requests", "decision_idempotency_key")
    op.drop_constraint(
        "fk_generation_default_change_request_evaluated_selection",
        "generation_default_change_requests",
        type_="foreignkey",
    )
    op.drop_column("generation_default_change_requests", "evaluated_against_selection_request_id")
