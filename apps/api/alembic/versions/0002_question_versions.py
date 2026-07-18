"""Create versioned questions, grading policies, and test-run records."""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_question_versions"
down_revision: Union[str, Sequence[str], None] = "0001_tenant_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def json_column(name: str, nullable: bool = False) -> sa.Column[object]:
    return sa.Column(name, sa.JSON(), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "grading_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_type", sa.String(length=20), nullable=False),
        sa.Column("policy_version", sa.String(length=20), nullable=False),
        json_column("json_schema"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_type", "policy_version", name="uq_grading_policy_version"),
    )
    op.create_table(
        "questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "question_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prompt", sa.String(length=10000), nullable=False),
        sa.Column("question_type", sa.String(length=20), nullable=False),
        sa.Column("grading_policy_id", sa.Uuid(), nullable=False),
        json_column("rule_json"),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        sa.ForeignKeyConstraint(["grading_policy_id"], ["grading_policies.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["published_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", "version_number", name="uq_question_version_number"),
    )
    op.create_table(
        "question_test_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        json_column("answer_json"),
        sa.Column("expected_decision", sa.String(length=30), nullable=False),
        sa.Column("expected_score", sa.Float(), nullable=False),
        json_column("expected_evidence_json"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_version_id", "category", name="uq_question_test_case_category"
        ),
    )
    op.create_table(
        "question_test_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_version_id", sa.Uuid(), nullable=False),
        sa.Column("grader_version", sa.String(length=100), nullable=False),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_summary", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["question_version_id"], ["question_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "question_test_case_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_test_run_id", sa.Uuid(), nullable=False),
        sa.Column("question_test_case_id", sa.Uuid(), nullable=False),
        sa.Column("decision", sa.String(length=30), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        json_column("evidence_json"),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("error_detail", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(["question_test_run_id"], ["question_test_runs.id"]),
        sa.ForeignKeyConstraint(["question_test_case_id"], ["question_test_cases.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("question_test_case_runs")
    op.drop_table("question_test_runs")
    op.drop_table("question_test_cases")
    op.drop_table("question_versions")
    op.drop_table("questions")
    op.drop_table("grading_policies")
