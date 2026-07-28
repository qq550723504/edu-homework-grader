"""Persist governed AI generation default selections and change requests."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0027_generation_default_governance"
down_revision: str | Sequence[str] | None = "0026_question_content_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


change_status = sa.Enum(
    "pending_approval",
    "approved",
    "rejected",
    "applied",
    "superseded",
    "rolled_back",
    name="generation_default_change_status",
    native_enum=False,
)


def upgrade() -> None:
    op.add_column("generation_jobs", sa.Column("provider_name", sa.String(length=100)))
    op.add_column("generation_jobs", sa.Column("model_version", sa.String(length=200)))
    op.add_column("generation_jobs", sa.Column("prompt_template_fingerprint", sa.String(length=64)))
    op.create_table(
        "generation_default_configurations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=200), nullable=False),
        sa.Column("prompt_version", sa.String(length=100), nullable=False),
        sa.Column("prompt_template_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider_name",
            "model_version",
            "prompt_version",
            "prompt_template_fingerprint",
            name="uq_generation_default_configuration_identity",
        ),
    )
    op.create_table(
        "generation_default_change_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("rollback_source_change_request_id", sa.Uuid()),
        sa.Column("status", change_status, nullable=False),
        sa.Column("request_reason", sa.String(length=1000), nullable=False),
        sa.Column("approval_reason", sa.String(length=1000)),
        sa.Column("application_reason", sa.String(length=1000)),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("evaluation_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("evaluation_record_digest", sa.String(length=64), nullable=False),
        sa.Column("evaluation_run_id", sa.String(length=200), nullable=False),
        sa.Column("evaluation_spec_id", sa.String(length=200), nullable=False),
        sa.Column("evaluation_watermark", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_summary_json", sa.JSON(), nullable=False),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid()),
        sa.Column("applied_by_user_id", sa.Uuid()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["configuration_id"], ["generation_default_configurations.id"]),
        sa.ForeignKeyConstraint(
            ["rollback_source_change_request_id"], ["generation_default_change_requests.id"]
        ),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["applied_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "submitted_by_user_id",
            "idempotency_key",
            name="uq_generation_default_change_request_idempotency",
        ),
    )
    op.create_table(
        "generation_default_selections",
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("configuration_id", sa.Uuid(), nullable=False),
        sa.Column("applied_change_request_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("scope = 'global'", name="ck_generation_default_scope_global"),
        sa.ForeignKeyConstraint(["configuration_id"], ["generation_default_configurations.id"]),
        sa.ForeignKeyConstraint(
            ["applied_change_request_id"], ["generation_default_change_requests.id"]
        ),
        sa.PrimaryKeyConstraint("scope"),
    )


def downgrade() -> None:
    op.drop_table("generation_default_selections")
    op.drop_table("generation_default_change_requests")
    op.drop_table("generation_default_configurations")
    op.drop_column("generation_jobs", "prompt_template_fingerprint")
    op.drop_column("generation_jobs", "model_version")
    op.drop_column("generation_jobs", "provider_name")
