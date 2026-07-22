"""Persist idempotent, ordered AI candidate batch acceptances."""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023_generation_batch_acceptances"
down_revision: Union[str, Sequence[str], None] = "0022_generation_quota_usages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_batch_acceptances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "actor_user_id",
            "idempotency_key",
            name="uq_generation_batch_acceptance_idempotency",
        ),
    )
    op.create_table(
        "generation_batch_acceptance_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_batch_acceptance_id", sa.Uuid(), nullable=False),
        sa.Column("generated_question_draft_id", sa.Uuid(), nullable=False),
        sa.Column("generated_question_review_decision_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_question_version_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["accepted_question_version_id"], ["question_versions.id"]),
        sa.ForeignKeyConstraint(["generated_question_draft_id"], ["generated_question_drafts.id"]),
        sa.ForeignKeyConstraint(
            ["generated_question_review_decision_id"], ["generated_question_review_decisions.id"]
        ),
        sa.ForeignKeyConstraint(
            ["generation_batch_acceptance_id"], ["generation_batch_acceptances.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generation_batch_acceptance_id",
            "position",
            name="uq_generation_batch_acceptance_item_position",
        ),
        sa.UniqueConstraint(
            "generation_batch_acceptance_id",
            "generated_question_draft_id",
            name="uq_generation_batch_acceptance_item_draft",
        ),
    )


def downgrade() -> None:
    op.drop_table("generation_batch_acceptance_items")
    op.drop_table("generation_batch_acceptances")
