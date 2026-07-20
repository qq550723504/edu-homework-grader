"""Track the replacement chain for review tasks."""

from collections import defaultdict
from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_review_task_replacement_chain"
down_revision: Union[str, Sequence[str], None] = "0010_answer_envelope_v1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_tasks") as batch:
        batch.add_column(sa.Column("superseded_by_task_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_review_tasks_superseded_by",
            "review_tasks",
            ["superseded_by_task_id"],
            ["id"],
        )
        batch.create_index("ix_review_tasks_superseded_by", ["superseded_by_task_id"], unique=False)
    _backfill_replacement_links()


def _backfill_replacement_links() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    tasks = sa.Table("review_tasks", metadata, autoload_with=bind)
    grouped: dict[object, list[dict[str, object]]] = defaultdict(list)
    for row in bind.execute(
        sa.select(tasks.c.id, tasks.c.attempt_answer_id, tasks.c.status, tasks.c.created_at)
    ).mappings():
        grouped[row["attempt_answer_id"]].append(dict(row))
    for chain in grouped.values():
        chain.sort(key=lambda task: (task["created_at"], task["id"]))
        for index, task in enumerate(chain[:-1]):
            if task["status"] == "superseded":
                bind.execute(
                    tasks.update()
                    .where(tasks.c.id == task["id"])
                    .values(superseded_by_task_id=chain[index + 1]["id"])
                )


def downgrade() -> None:
    with op.batch_alter_table("review_tasks") as batch:
        batch.drop_index("ix_review_tasks_superseded_by")
        batch.drop_constraint("fk_review_tasks_superseded_by", type_="foreignkey")
        batch.drop_column("superseded_by_task_id")
