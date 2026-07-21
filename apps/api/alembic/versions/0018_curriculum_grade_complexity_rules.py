"""Persist per-grade curriculum complexity rules."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_curriculum_grade_complexity_rules"
down_revision: Union[str, Sequence[str], None] = "0017_question_prompt_fingerprints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "curriculum_grade_mappings",
        sa.Column(
            "complexity_rules_json",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("curriculum_grade_mappings", "complexity_rules_json")
