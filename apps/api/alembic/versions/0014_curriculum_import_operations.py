"""Persist operational governance for curated curriculum imports."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_curriculum_import_operations"
down_revision: Union[str, Sequence[str], None] = "0013_curriculum_profile_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("curriculum_source_records") as batch:
        batch.add_column(sa.Column("license", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("document_number", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("curated_at", sa.Date(), nullable=True))

    with op.batch_alter_table("curriculum_objective_revisions") as batch:
        batch.add_column(sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
        batch.add_column(sa.Column("change_summary", sa.String(length=1000), nullable=True))
        batch.create_foreign_key(
            "fk_curriculum_revision_created_by_user",
            "users",
            ["created_by_user_id"],
            ["id"],
        )

    op.create_table(
        "curriculum_import_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("input_format", sa.String(length=10), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("baseline_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("submitted_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_summary", sa.String(length=1000), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["activated_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["curriculum_profiles.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_curriculum_import_batches_profile_status",
        "curriculum_import_batches",
        ["profile_id", "status"],
    )
    op.create_index(
        "ix_curriculum_import_batches_digest_status",
        "curriculum_import_batches",
        ["content_digest", "status"],
    )
    op.create_table(
        "curriculum_import_issues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=False),
        sa.Column("source_path", sa.String(length=500), nullable=True),
        sa.Column("source_row", sa.Integer(), nullable=True),
        sa.Column("source_column", sa.String(length=100), nullable=True),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_id"], ["curriculum_import_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "batch_id",
            "source_path",
            "source_row",
            "source_column",
            "code",
            name="uq_curriculum_import_issue_location",
        ),
    )


def downgrade() -> None:
    op.drop_table("curriculum_import_issues")
    op.drop_index(
        "ix_curriculum_import_batches_digest_status", table_name="curriculum_import_batches"
    )
    op.drop_index(
        "ix_curriculum_import_batches_profile_status", table_name="curriculum_import_batches"
    )
    op.drop_table("curriculum_import_batches")

    with op.batch_alter_table("curriculum_objective_revisions") as batch:
        batch.drop_constraint("fk_curriculum_revision_created_by_user", type_="foreignkey")
        batch.drop_column("change_summary")
        batch.drop_column("created_by_user_id")

    with op.batch_alter_table("curriculum_source_records") as batch:
        batch.drop_column("curated_at")
        batch.drop_column("document_number")
        batch.drop_column("license")
