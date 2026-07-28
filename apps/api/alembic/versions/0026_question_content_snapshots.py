"""Persist versioned question-content and source-license snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0026_question_content_snapshots"
down_revision: str | Sequence[str] | None = "0025_student_activations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


QUESTION_CONTENT_SCHEMA_VERSION = "question-content-v1"


def _legacy_question_content(prompt: str, reading_material: str | None) -> dict[str, object]:
    return {
        "stem": [{"kind": "text", "text": prompt}],
        "reading_material": (
            [] if reading_material is None else [{"kind": "text", "text": reading_material}]
        ),
        "response": {"kind": "legacy-rule"},
        "explanation": [],
        "metadata": {"grade": None, "difficulty": None, "estimated_minutes": None},
    }


def upgrade() -> None:
    op.add_column(
        "question_versions",
        sa.Column("content_schema_version", sa.String(length=40), nullable=True),
    )
    op.add_column("question_versions", sa.Column("content_json", sa.JSON(), nullable=True))

    question_versions = sa.table(
        "question_versions",
        sa.column("id"),
        sa.column("prompt", sa.String()),
        sa.column("reading_material", sa.Text()),
        sa.column("content_schema_version", sa.String()),
        sa.column("content_json", sa.JSON()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            question_versions.c.id,
            question_versions.c.prompt,
            question_versions.c.reading_material,
        )
    )
    for row in rows:
        connection.execute(
            question_versions.update()
            .where(question_versions.c.id == row.id)
            .values(
                content_schema_version=QUESTION_CONTENT_SCHEMA_VERSION,
                content_json=_legacy_question_content(row.prompt, row.reading_material),
            )
        )

    with op.batch_alter_table("question_versions") as batch:
        batch.alter_column(
            "content_schema_version", existing_type=sa.String(length=40), nullable=False
        )
        batch.alter_column("content_json", existing_type=sa.JSON(), nullable=False)

    op.create_table(
        "question_media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("alt_text", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_question_media_asset_byte_size_nonnegative"),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_version_id", "position", name="uq_question_media_asset_position"
        ),
    )
    op.create_index(
        "ix_question_media_assets_question_version_id",
        "question_media_assets",
        ["question_version_id"],
    )
    op.create_table(
        "external_content_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=500), nullable=False),
        sa.Column("source_version", sa.String(length=100), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("license_code", sa.String(length=100), nullable=False),
        sa.Column("license_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("tenant_scope_id", sa.Uuid(), nullable=False),
        sa.Column("allow_persist", sa.Boolean(), nullable=False),
        sa.Column("allow_student_display", sa.Boolean(), nullable=False),
        sa.Column("allow_ai_processing", sa.Boolean(), nullable=False),
        sa.Column("allow_redistribution", sa.Boolean(), nullable=False),
        sa.Column("contract_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"]),
        sa.ForeignKeyConstraint(["tenant_scope_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_version_id",
            "provider",
            "external_id",
            "source_version",
            name="uq_external_content_reference_identity",
        ),
    )
    op.create_index(
        "ix_external_content_references_question_version_id",
        "external_content_references",
        ["question_version_id"],
    )
    op.create_index(
        "ix_external_content_references_provider",
        "external_content_references",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_table("external_content_references")
    op.drop_table("question_media_assets")
    op.drop_column("question_versions", "content_json")
    op.drop_column("question_versions", "content_schema_version")
