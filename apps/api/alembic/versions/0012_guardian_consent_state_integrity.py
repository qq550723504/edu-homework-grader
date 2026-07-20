"""Reject contradictory guardian-consent states.

Existing rows that require guardian consent but were incorrectly marked
``not_required`` are safely moved to ``pending`` before the stronger database
constraint is installed.  That preserves fail-closed behavior and requires an
administrator to explicitly verify any future grant.
"""

from collections.abc import Sequence
from typing import Union

from alembic import op


revision: str = "0012_guardian_consent_state_integrity"
down_revision: Union[str, Sequence[str], None] = "0011_review_task_replacement_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSTRAINT = "ck_guardian_consent_status_matches_requirement"
_STRICT_CONDITION = (
    "(requires_guardian_consent = false AND status = 'not_required') "
    "OR (requires_guardian_consent = true AND status != 'not_required')"
)
_LEGACY_CONDITION = (
    "(requires_guardian_consent = false AND status = 'not_required') "
    "OR requires_guardian_consent = true"
)


def upgrade() -> None:
    op.execute(
        "UPDATE student_guardian_consents "
        "SET status = 'pending', notice_version = NULL, evidence_reference = NULL, "
        "verified_by_user_id = NULL, granted_at = NULL "
        "WHERE requires_guardian_consent = true AND status = 'not_required'"
    )
    op.drop_constraint(_CONSTRAINT, "student_guardian_consents", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "student_guardian_consents",
        _STRICT_CONDITION,
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "student_guardian_consents", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "student_guardian_consents",
        _LEGACY_CONDITION,
    )
