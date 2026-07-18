"""Create student appeals and correction-attempt links."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_student_appeals_and_corrections"
down_revision: Union[str, Sequence[str], None] = "0005_teacher_review_and_publication"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_appeals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("original_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("decision_reason", sa.String(2000)),
        sa.Column("decided_by_user_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["original_attempt_id"], ["student_attempts.id"]),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"]),
    )
    op.create_table(
        "correction_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("original_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("correction_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("appeal_id", sa.Uuid(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["original_attempt_id"], ["student_attempts.id"]),
        sa.ForeignKeyConstraint(["correction_attempt_id"], ["student_attempts.id"]),
        sa.ForeignKeyConstraint(["appeal_id"], ["review_appeals.id"]),
    )


def downgrade() -> None:
    op.drop_table("correction_attempts")
    op.drop_table("review_appeals")
