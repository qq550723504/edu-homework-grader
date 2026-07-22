"""Persist E4 reading material separately from the question prompt."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_question_version_reading_material"
down_revision: Union[str, Sequence[str], None] = "0019_ai_generated_question_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "question_versions",
        sa.Column("reading_material", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("question_versions", "reading_material")
