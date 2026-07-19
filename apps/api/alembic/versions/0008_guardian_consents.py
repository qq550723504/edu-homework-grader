"""Create school-verified guardian consent records."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_guardian_consents"
down_revision: Union[str, Sequence[str], None] = "0007_privacy_audit_foundation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "student_guardian_consents",
        sa.Column("student_id", sa.Uuid(), primary_key=True),
        sa.Column("requires_guardian_consent", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("notice_version", sa.String(50)),
        sa.Column("evidence_reference", sa.String(100)),
        sa.Column("verified_by_user_id", sa.Uuid()),
        sa.Column("granted_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True)),
        sa.Column("withdrawal_reason", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "(requires_guardian_consent = false AND status = 'not_required') "
            "OR requires_guardian_consent = true",
            name="ck_guardian_consent_status_matches_requirement",
        ),
        sa.CheckConstraint(
            "status != 'granted' OR (notice_version IS NOT NULL "
            "AND evidence_reference IS NOT NULL AND verified_by_user_id IS NOT NULL "
            "AND granted_at IS NOT NULL)",
            name="ck_granted_guardian_consent_has_verification",
        ),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["verified_by_user_id"], ["users.id"]),
    )
    op.create_index("ix_student_guardian_consents_status", "student_guardian_consents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_student_guardian_consents_status", table_name="student_guardian_consents")
    op.drop_table("student_guardian_consents")
