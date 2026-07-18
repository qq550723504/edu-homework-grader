"""Create teacher review tasks, decisions, and grade publications."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005_teacher_review_and_publication"
down_revision: Union[str, Sequence[str], None] = "0004_english_grading_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_answer_id", sa.Uuid(), nullable=False),
        sa.Column("grading_run_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("active_key", sa.String(length=10)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["attempt_answer_id"], ["attempt_answers.id"]),
        sa.ForeignKeyConstraint(["grading_run_id"], ["grading_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_answer_id", "active_key", name="uq_review_task_active_answer"),
    )
    op.create_index("ix_review_tasks_queue", "review_tasks", ["status", "reason", "created_at"])
    op.create_index("ix_review_tasks_grading_run", "review_tasks", ["grading_run_id"])
    op.create_table(
        "review_decisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("review_task_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=30), nullable=False),
        sa.Column("original_score", sa.Float(), nullable=False),
        sa.Column("final_score", sa.Float()),
        sa.Column("reason", sa.String(length=2_000)),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["review_task_id"], ["review_tasks.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "grade_publications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["student_attempts.id"]),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", name="uq_grade_publication_attempt"),
    )


def downgrade() -> None:
    op.drop_table("grade_publications")
    op.drop_table("review_decisions")
    op.drop_index("ix_review_tasks_grading_run", table_name="review_tasks")
    op.drop_index("ix_review_tasks_queue", table_name="review_tasks")
    op.drop_table("review_tasks")
