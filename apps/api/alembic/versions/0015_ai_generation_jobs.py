"""Persist governed AI generation jobs, attempts, and candidate drafts."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_ai_generation_jobs"
down_revision: Union[str, Sequence[str], None] = "0014_curriculum_import_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("teacher_user_id", sa.Uuid(), nullable=False),
        sa.Column("curriculum_profile_id", sa.Uuid(), nullable=True),
        sa.Column("curriculum_objective_revision_id", sa.Uuid(), nullable=False),
        sa.Column("grade", sa.String(length=100), nullable=True),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("distribution_json", sa.JSON(), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=100), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=True),
        sa.Column("succeeded_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("total_cost_usd", sa.Float(), nullable=True),
        sa.Column("total_duration_ms", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "requested_count > 0", name="ck_generation_job_requested_count_positive"
        ),
        sa.ForeignKeyConstraint(
            ["curriculum_objective_revision_id"], ["curriculum_objective_revisions.id"]
        ),
        sa.ForeignKeyConstraint(["curriculum_profile_id"], ["curriculum_profiles.id"]),
        sa.ForeignKeyConstraint(["teacher_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_generation_job_idempotency"),
    )
    op.create_index("ix_generation_jobs_tenant_status", "generation_jobs", ["tenant_id", "status"])
    op.create_index(
        "ix_generation_jobs_teacher_created", "generation_jobs", ["teacher_user_id", "created_at"]
    )

    op.create_table(
        "generation_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_summary", sa.JSON(), nullable=True),
        sa.Column("response_summary", sa.JSON(), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["generation_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_generation_attempt_number"),
    )

    op.create_table(
        "generated_question_drafts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("generation_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("validation_errors_json", sa.JSON(), nullable=True),
        sa.Column("teacher_state", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["generation_attempt_id"], ["generation_attempts.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["generation_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_generated_question_draft_ordinal"),
    )
    op.create_index(
        "ix_generated_question_drafts_content_hash", "generated_question_drafts", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_generated_question_drafts_content_hash", table_name="generated_question_drafts"
    )
    op.drop_table("generated_question_drafts")
    op.drop_table("generation_attempts")
    op.drop_index("ix_generation_jobs_teacher_created", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_tenant_status", table_name="generation_jobs")
    op.drop_table("generation_jobs")
