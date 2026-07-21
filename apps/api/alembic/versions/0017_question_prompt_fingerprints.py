"""Persist versioned prompt fingerprints for duplicate detection."""

from collections.abc import Sequence
from hashlib import sha256
import json
import re
from typing import Union
import unicodedata

from alembic import op
import sqlalchemy as sa


revision: str = "0017_question_prompt_fingerprints"
down_revision: Union[str, Sequence[str], None] = "0016_ai_question_validation_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


FINGERPRINT_VERSION = "question-fingerprint-v1"
_WHITESPACE = re.compile(r"\s+")


def _normalize_prompt(prompt: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", prompt).strip()).casefold()


def _fingerprints(prompt: str) -> tuple[str, str, str]:
    return (
        FINGERPRINT_VERSION,
        sha256(prompt.encode("utf-8")).hexdigest(),
        sha256(_normalize_prompt(prompt).encode("utf-8")).hexdigest(),
    )


def _draft_prompt(candidate_json: object) -> str:
    if isinstance(candidate_json, str):
        try:
            candidate_json = json.loads(candidate_json)
        except json.JSONDecodeError:
            return ""
    if isinstance(candidate_json, dict) and isinstance(prompt := candidate_json.get("prompt"), str):
        return prompt
    return ""


def upgrade() -> None:
    for table_name in ("generated_question_drafts", "question_versions"):
        op.add_column(
            table_name, sa.Column("fingerprint_version", sa.String(length=100), nullable=True)
        )
        op.add_column(
            table_name, sa.Column("exact_prompt_hash", sa.String(length=64), nullable=True)
        )
        op.add_column(
            table_name, sa.Column("normalized_prompt_hash", sa.String(length=64), nullable=True)
        )

    bind = op.get_bind()
    question_versions = sa.table(
        "question_versions",
        sa.column("id", sa.Uuid()),
        sa.column("prompt", sa.String()),
        sa.column("fingerprint_version", sa.String()),
        sa.column("exact_prompt_hash", sa.String()),
        sa.column("normalized_prompt_hash", sa.String()),
    )
    for question_version_id, prompt in bind.execute(
        sa.select(question_versions.c.id, question_versions.c.prompt)
    ):
        version, exact_hash, normalized_hash = _fingerprints(prompt)
        bind.execute(
            question_versions.update()
            .where(question_versions.c.id == question_version_id)
            .values(
                fingerprint_version=version,
                exact_prompt_hash=exact_hash,
                normalized_prompt_hash=normalized_hash,
            )
        )

    generated_drafts = sa.table(
        "generated_question_drafts",
        sa.column("id", sa.Uuid()),
        sa.column("candidate_json", sa.JSON()),
        sa.column("fingerprint_version", sa.String()),
        sa.column("exact_prompt_hash", sa.String()),
        sa.column("normalized_prompt_hash", sa.String()),
    )
    for draft_id, candidate_json in bind.execute(
        sa.select(generated_drafts.c.id, generated_drafts.c.candidate_json)
    ):
        version, exact_hash, normalized_hash = _fingerprints(_draft_prompt(candidate_json))
        bind.execute(
            generated_drafts.update()
            .where(generated_drafts.c.id == draft_id)
            .values(
                fingerprint_version=version,
                exact_prompt_hash=exact_hash,
                normalized_prompt_hash=normalized_hash,
            )
        )

    for table_name in ("generated_question_drafts", "question_versions"):
        op.alter_column(table_name, "fingerprint_version", nullable=False)
        op.alter_column(table_name, "exact_prompt_hash", nullable=False)
        op.alter_column(table_name, "normalized_prompt_hash", nullable=False)

    op.create_index(
        "ix_generated_question_drafts_job_fingerprint_exact",
        "generated_question_drafts",
        ["job_id", "fingerprint_version", "exact_prompt_hash"],
    )
    op.create_index(
        "ix_generated_question_drafts_job_fingerprint_normalized",
        "generated_question_drafts",
        ["job_id", "fingerprint_version", "normalized_prompt_hash"],
    )
    op.create_index(
        "ix_question_versions_fingerprint_exact",
        "question_versions",
        ["fingerprint_version", "exact_prompt_hash"],
    )
    op.create_index(
        "ix_question_versions_fingerprint_normalized",
        "question_versions",
        ["fingerprint_version", "normalized_prompt_hash"],
    )
    op.create_index("ix_questions_tenant_id", "questions", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_questions_tenant_id", table_name="questions")
    op.drop_index("ix_question_versions_fingerprint_normalized", table_name="question_versions")
    op.drop_index("ix_question_versions_fingerprint_exact", table_name="question_versions")
    op.drop_index(
        "ix_generated_question_drafts_job_fingerprint_normalized",
        table_name="generated_question_drafts",
    )
    op.drop_index(
        "ix_generated_question_drafts_job_fingerprint_exact",
        table_name="generated_question_drafts",
    )
    for table_name in ("generated_question_drafts", "question_versions"):
        op.drop_column(table_name, "normalized_prompt_hash")
        op.drop_column(table_name, "exact_prompt_hash")
        op.drop_column(table_name, "fingerprint_version")
