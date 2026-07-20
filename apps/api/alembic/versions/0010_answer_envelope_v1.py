"""Migrate persisted answers to the versioned answer envelope."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

from edu_grader_api.answer_envelope import migrate_legacy_answer_envelope


revision: str = "0010_answer_envelope_v1"
down_revision: Union[str, Sequence[str], None] = "0009_privacy_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _migrate_column(table_name: str, column_name: str) -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    table = sa.Table(table_name, metadata, autoload_with=bind)
    rows = bind.execute(sa.select(table.c.id, table.c[column_name])).mappings()
    for row in rows:
        current = row[column_name]
        if not isinstance(current, dict):
            continue
        migrated = migrate_legacy_answer_envelope(current)
        if migrated != current:
            bind.execute(
                table.update().where(table.c.id == row["id"]).values({column_name: migrated})
            )


def upgrade() -> None:
    _migrate_column("attempt_answers", "answer_json")
    _migrate_column("grading_runs", "answer_snapshot_json")


def downgrade() -> None:
    # The former heterogeneous answer shapes cannot be reconstructed safely.
    pass
