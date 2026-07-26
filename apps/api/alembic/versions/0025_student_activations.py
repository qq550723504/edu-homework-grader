"""Add student activation lifecycle records."""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0025_student_activations"
down_revision: Union[str, Sequence[str], None] = "0024_generation_governance_entries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_activations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("keycloak_user_id", sa.String(length=255)),
        sa.Column("code_hmac", sa.String(length=64)),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True)),
        sa.Column("disclosed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("expired_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.String(length=200)),
        sa.Column("issued_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(["issued_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status != 'issued' OR (code_hmac IS NOT NULL AND expires_at IS NOT NULL AND keycloak_user_id IS NOT NULL)",
            name="ck_student_activations_issued_has_credential",
        ),
    )
    op.create_index(
        "ix_student_activations_student_status", "student_activations", ["student_id", "status"]
    )
    op.create_index(
        "ix_student_activations_status_expires_at", "student_activations", ["status", "expires_at"]
    )


def downgrade() -> None:
    op.drop_table("student_activations")
