"""Create immutable grading runs and signals."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_english_grading_runs"
down_revision: Union[str, Sequence[str], None] = "0003_student_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _json(name: str) -> sa.Column[object]:
    return sa.Column(name, sa.JSON(), nullable=False)


def upgrade() -> None:
    op.create_table(
        "grading_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_answer_id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("grading_policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_version", sa.String(length=20), nullable=False),
        _json("rule_snapshot_json"),
        _json("answer_snapshot_json"),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column("grader_version", sa.String(length=100), nullable=False),
        _json("dependency_versions_json"),
        _json("thresholds_json"),
        _json("evidence_json"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_answer_id"], ["attempt_answers.id"]),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"]),
        sa.ForeignKeyConstraint(["grading_policy_id"], ["grading_policies.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_grading_runs_attempt_answer", "grading_runs", ["attempt_answer_id"])
    op.create_table(
        "grading_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("grading_run_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=True),
        _json("evidence_json"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["grading_run_id"], ["grading_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grading_run_id", "ordinal", name="uq_grading_signal_run_ordinal"),
    )


def downgrade() -> None:
    op.drop_table("grading_signals")
    op.drop_index("ix_grading_runs_attempt_answer", table_name="grading_runs")
    op.drop_table("grading_runs")
