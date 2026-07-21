"""Persist immutable AI candidate-question validation runs and findings."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_ai_question_validation_runs"
down_revision: Union[str, Sequence[str], None] = "0015_ai_generation_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_validation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generated_question_draft_id", sa.Uuid(), nullable=False),
        sa.Column("generation_job_id", sa.Uuid(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("validator_version", sa.String(length=100), nullable=False),
        sa.Column("ruleset_version", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("feature_summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('passed', 'warning', 'blocked')",
            name="ck_generation_validation_run_status",
        ),
        sa.ForeignKeyConstraint(["generated_question_draft_id"], ["generated_question_drafts.id"]),
        sa.ForeignKeyConstraint(["generation_job_id"], ["generation_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_question_draft_id",
            "run_number",
            name="uq_generation_validation_run_draft_number",
        ),
    )
    op.create_index(
        "ix_generation_validation_runs_draft_created",
        "generation_validation_runs",
        ["generated_question_draft_id", "created_at"],
    )
    op.create_index(
        "ix_generation_validation_runs_job_created",
        "generation_validation_runs",
        ["generation_job_id", "created_at"],
    )

    op.create_table(
        "validation_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("validation_run_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=30), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("remediation", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "severity IN ('warning', 'blocked')",
            name="ck_validation_finding_severity",
        ),
        sa.ForeignKeyConstraint(["validation_run_id"], ["generation_validation_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_validation_findings_run_created",
        "validation_findings",
        ["validation_run_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_validation_findings_run_created", table_name="validation_findings")
    op.drop_table("validation_findings")
    op.drop_index(
        "ix_generation_validation_runs_job_created", table_name="generation_validation_runs"
    )
    op.drop_index(
        "ix_generation_validation_runs_draft_created", table_name="generation_validation_runs"
    )
    op.drop_table("generation_validation_runs")
