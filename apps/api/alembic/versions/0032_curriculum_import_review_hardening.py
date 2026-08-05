"""Add curriculum import review snapshots and idempotency metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0032_curriculum_import_review_hardening"
down_revision: str | Sequence[str] | None = "0031_operational_evaluation_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table, column in (
        ("curriculum_profiles", "retire_idempotency_key"),
        ("curriculum_import_batches", "create_idempotency_key"),
        ("curriculum_import_batches", "submit_idempotency_key"),
        ("curriculum_import_batches", "review_idempotency_key"),
        ("curriculum_import_batches", "activate_idempotency_key"),
    ):
        op.add_column(table, sa.Column(column, sa.String(length=128), nullable=True))

    for table, column in (
        ("curriculum_profiles", "retire_request_digest"),
        ("curriculum_import_batches", "create_request_digest"),
        ("curriculum_import_batches", "submit_request_digest"),
        ("curriculum_import_batches", "review_request_digest"),
        ("curriculum_import_batches", "activate_request_digest"),
    ):
        op.add_column(table, sa.Column(column, sa.String(length=64), nullable=True))

    op.create_unique_constraint(
        "uq_curriculum_profiles_retire_key",
        "curriculum_profiles",
        ["retire_idempotency_key"],
    )
    for column, name in (
        ("create_idempotency_key", "uq_curriculum_import_batches_create_key"),
        ("submit_idempotency_key", "uq_curriculum_import_batches_submit_key"),
        ("review_idempotency_key", "uq_curriculum_import_batches_review_key"),
        ("activate_idempotency_key", "uq_curriculum_import_batches_activate_key"),
    ):
        op.create_unique_constraint(name, "curriculum_import_batches", [column])


def downgrade() -> None:
    for name in (
        "uq_curriculum_import_batches_activate_key",
        "uq_curriculum_import_batches_review_key",
        "uq_curriculum_import_batches_submit_key",
        "uq_curriculum_import_batches_create_key",
    ):
        op.drop_constraint(name, "curriculum_import_batches", type_="unique")
    op.drop_constraint("uq_curriculum_profiles_retire_key", "curriculum_profiles", type_="unique")

    for table, column in (
        ("curriculum_import_batches", "activate_request_digest"),
        ("curriculum_import_batches", "review_request_digest"),
        ("curriculum_import_batches", "submit_request_digest"),
        ("curriculum_import_batches", "create_request_digest"),
        ("curriculum_profiles", "retire_request_digest"),
        ("curriculum_import_batches", "activate_idempotency_key"),
        ("curriculum_import_batches", "review_idempotency_key"),
        ("curriculum_import_batches", "submit_idempotency_key"),
        ("curriculum_import_batches", "create_idempotency_key"),
        ("curriculum_profiles", "retire_idempotency_key"),
    ):
        op.drop_column(table, column)
