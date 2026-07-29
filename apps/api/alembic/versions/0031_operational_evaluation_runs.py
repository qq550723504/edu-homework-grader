"""Persist signed operational evaluation run metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0031_operational_evaluation_runs"
down_revision: str | Sequence[str] | None = "0030_revalidate_generation_default_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


run_status = sa.Enum(
    "queued",
    "running",
    "succeeded",
    "failed",
    name="operational_evaluation_run_status",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "operational_evaluation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("github_run_id", sa.String(length=100), nullable=False),
        sa.Column("repository_id", sa.String(length=100), nullable=False),
        sa.Column("repository_owner_id", sa.String(length=100), nullable=False),
        sa.Column("workflow_ref", sa.String(length=500), nullable=False),
        sa.Column("spec_digest", sa.String(length=64), nullable=False),
        sa.Column("callback_token_digest", sa.String(length=64)),
        sa.Column("status", run_status, nullable=False),
        sa.Column("report_json", sa.JSON()),
        sa.Column("report_sha256", sa.String(length=64)),
        sa.Column("failure_code", sa.String(length=100)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_run_id", name="uq_operational_evaluation_runs_github_run"),
    )
    op.create_index(
        "ix_operational_evaluation_runs_expiry",
        "operational_evaluation_runs",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_operational_evaluation_runs_expiry", table_name="operational_evaluation_runs")
    op.drop_table("operational_evaluation_runs")
