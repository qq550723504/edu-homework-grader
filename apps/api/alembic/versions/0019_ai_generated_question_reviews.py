"""Persist immutable AI candidate review revisions and decisions."""

from collections.abc import Sequence
from typing import Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0019_ai_generated_question_reviews"
down_revision: Union[str, Sequence[str], None] = "0018_curriculum_grade_complexity_rules"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _install_append_only_evidence_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE FUNCTION prevent_generated_question_evidence_mutation() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'generated question evidence is append-only';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER generated_question_draft_revisions_no_update_or_delete
        BEFORE UPDATE OR DELETE ON generated_question_draft_revisions
        FOR EACH ROW EXECUTE FUNCTION prevent_generated_question_evidence_mutation();
        CREATE TRIGGER generated_question_review_decisions_no_update_or_delete
        BEFORE UPDATE OR DELETE ON generated_question_review_decisions
        FOR EACH ROW EXECUTE FUNCTION prevent_generated_question_evidence_mutation();
        CREATE TRIGGER generation_validation_runs_no_update_or_delete
        BEFORE UPDATE OR DELETE ON generation_validation_runs
        FOR EACH ROW EXECUTE FUNCTION prevent_generated_question_evidence_mutation();
        """
    )


def _remove_append_only_evidence_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        DROP TRIGGER IF EXISTS generation_validation_runs_no_update_or_delete
        ON generation_validation_runs;
        DROP TRIGGER IF EXISTS generated_question_review_decisions_no_update_or_delete
        ON generated_question_review_decisions;
        DROP TRIGGER IF EXISTS generated_question_draft_revisions_no_update_or_delete
        ON generated_question_draft_revisions;
        DROP FUNCTION IF EXISTS prevent_generated_question_evidence_mutation();
        """
    )


def upgrade() -> None:
    op.create_table(
        "generated_question_draft_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generated_question_draft_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("editor_user_id", sa.Uuid(), nullable=True),
        # System-created revision 1 has no teacher write request to replay.
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("request_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["editor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["generated_question_draft_id"], ["generated_question_drafts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_question_draft_id",
            "idempotency_key",
            name="uq_generated_question_draft_revision_idempotency",
        ),
        sa.UniqueConstraint(
            "generated_question_draft_id",
            "revision_number",
            name="uq_generated_question_draft_revision_number",
        ),
        sa.UniqueConstraint(
            "id",
            "generated_question_draft_id",
            name="uq_generated_question_draft_revision_pair",
        ),
    )

    with op.batch_alter_table("generated_question_drafts") as batch_op:
        batch_op.add_column(sa.Column("current_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_generated_question_drafts_current_revision_pair",
            "generated_question_draft_revisions",
            ["current_revision_id", "id"],
            ["id", "generated_question_draft_id"],
            deferrable=True,
            initially="DEFERRED",
        )
    with op.batch_alter_table("generation_validation_runs") as batch_op:
        batch_op.add_column(sa.Column("draft_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_unique_constraint(
            "uq_generation_validation_run_evidence_pair",
            ["id", "generated_question_draft_id", "draft_revision_id"],
        )
        batch_op.create_foreign_key(
            "fk_generation_validation_runs_revision_pair",
            "generated_question_draft_revisions",
            ["draft_revision_id", "generated_question_draft_id"],
            ["id", "generated_question_draft_id"],
        )

    bind = op.get_bind()
    generated_drafts = sa.table(
        "generated_question_drafts",
        sa.column("id", sa.Uuid()),
        sa.column("candidate_json", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("current_revision_id", sa.Uuid()),
    )
    draft_revisions = sa.table(
        "generated_question_draft_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("generated_question_draft_id", sa.Uuid()),
        sa.column("revision_number", sa.Integer()),
        sa.column("candidate_json", sa.JSON()),
        sa.column("content_hash", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    revision_ids: dict[object, object] = {}
    for draft_id, candidate_json, content_hash in bind.execute(
        sa.select(
            generated_drafts.c.id,
            generated_drafts.c.candidate_json,
            generated_drafts.c.content_hash,
        )
    ):
        revision_id = uuid4()
        revision_ids[draft_id] = revision_id
        bind.execute(
            draft_revisions.insert().values(
                id=revision_id,
                generated_question_draft_id=draft_id,
                revision_number=1,
                candidate_json=candidate_json,
                content_hash=content_hash,
                created_at=sa.func.now(),
            )
        )
        bind.execute(
            generated_drafts.update()
            .where(generated_drafts.c.id == draft_id)
            .values(current_revision_id=revision_id)
        )

    validation_runs = sa.table(
        "generation_validation_runs",
        sa.column("id", sa.Uuid()),
        sa.column("generated_question_draft_id", sa.Uuid()),
        sa.column("draft_revision_id", sa.Uuid()),
    )
    for run_id, draft_id in bind.execute(
        sa.select(validation_runs.c.id, validation_runs.c.generated_question_draft_id)
    ):
        bind.execute(
            validation_runs.update()
            .where(validation_runs.c.id == run_id)
            .values(draft_revision_id=revision_ids[draft_id])
        )

    with op.batch_alter_table("generated_question_drafts") as batch_op:
        batch_op.alter_column("current_revision_id", nullable=False)
    with op.batch_alter_table("generation_validation_runs") as batch_op:
        batch_op.alter_column("draft_revision_id", nullable=False)

    op.create_table(
        "generated_question_review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generated_question_draft_id", sa.Uuid(), nullable=False),
        sa.Column("draft_revision_id", sa.Uuid(), nullable=False),
        sa.Column("generation_validation_run_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("reason", sa.String(length=4_000), nullable=True),
        sa.Column("warning_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_question_version_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["accepted_question_version_id"], ["question_versions.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["draft_revision_id", "generated_question_draft_id"],
            [
                "generated_question_draft_revisions.id",
                "generated_question_draft_revisions.generated_question_draft_id",
            ],
            name="fk_generated_question_review_decisions_revision_pair",
        ),
        sa.ForeignKeyConstraint(
            [
                "generation_validation_run_id",
                "generated_question_draft_id",
                "draft_revision_id",
            ],
            [
                "generation_validation_runs.id",
                "generation_validation_runs.generated_question_draft_id",
                "generation_validation_runs.draft_revision_id",
            ],
            name="fk_generated_question_review_decisions_validation_run_pair",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "generated_question_draft_id",
            "action",
            "idempotency_key",
            name="uq_generated_question_review_decision_idempotency",
        ),
    )
    _install_append_only_evidence_triggers()


def downgrade() -> None:
    _remove_append_only_evidence_triggers()
    op.drop_table("generated_question_review_decisions")
    with op.batch_alter_table("generation_validation_runs") as batch_op:
        batch_op.drop_constraint("fk_generation_validation_runs_revision_pair", type_="foreignkey")
        batch_op.drop_constraint("uq_generation_validation_run_evidence_pair", type_="unique")
        batch_op.drop_column("draft_revision_id")
    with op.batch_alter_table("generated_question_drafts") as batch_op:
        batch_op.drop_constraint(
            "fk_generated_question_drafts_current_revision_pair", type_="foreignkey"
        )
        batch_op.drop_column("current_revision_id")
    op.drop_table("generated_question_draft_revisions")
