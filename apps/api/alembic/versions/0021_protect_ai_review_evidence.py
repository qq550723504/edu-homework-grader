"""Protect provider originals and validation findings from mutation."""

from collections.abc import Sequence
from typing import Union

from alembic import op


revision: str = "0021_protect_ai_review_evidence"
down_revision: Union[str, Sequence[str], None] = "0020_question_version_reading_material"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _install_review_evidence_protection_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE FUNCTION prevent_generated_question_draft_candidate_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'generated question provider candidate is immutable';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER generated_question_drafts_candidate_json_no_update
        BEFORE UPDATE OF candidate_json ON generated_question_drafts
        FOR EACH ROW
        WHEN (OLD.candidate_json::jsonb IS DISTINCT FROM NEW.candidate_json::jsonb)
        EXECUTE FUNCTION prevent_generated_question_draft_candidate_mutation();
        CREATE TRIGGER validation_findings_no_update_or_delete
        BEFORE UPDATE OR DELETE ON validation_findings
        FOR EACH ROW EXECUTE FUNCTION prevent_generated_question_evidence_mutation();
        """
    )


def _remove_review_evidence_protection_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        DROP TRIGGER IF EXISTS validation_findings_no_update_or_delete
        ON validation_findings;
        DROP TRIGGER IF EXISTS generated_question_drafts_candidate_json_no_update
        ON generated_question_drafts;
        DROP FUNCTION IF EXISTS prevent_generated_question_draft_candidate_mutation();
        """
    )


def upgrade() -> None:
    _install_review_evidence_protection_triggers()


def downgrade() -> None:
    _remove_review_evidence_protection_triggers()
