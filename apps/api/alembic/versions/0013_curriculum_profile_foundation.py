"""Create the governed, versioned curriculum profile catalogue.

The initial rows are editorially curated identifiers and short summaries. They
intentionally retain source metadata rather than copying curriculum or textbook
content, so a future source import remains a separate reviewed operation.
"""

from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Union
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "0013_curriculum_profile_foundation"
down_revision: Union[str, Sequence[str], None] = "0012_guardian_consent_state_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SOURCES = (
    (
        UUID("00000000-0000-0000-0000-000000000131"),
        "Ministry of Education of the PRC",
        "3—6岁儿童学习与发展指南",
        "https://www.moe.gov.cn/srcsite/A06/s3327/201210/t20121009_143254.html",
        "2012",
        date(2012, 10, 9),
    ),
    (
        UUID("00000000-0000-0000-0000-000000000132"),
        "Ministry of Education of the PRC",
        "义务教育课程方案和课程标准（2022年版）",
        "https://www.moe.gov.cn/srcsite/A26/s8001/202204/t20220420_619921.html",
        "2022",
        date(2022, 3, 25),
    ),
    (
        UUID("00000000-0000-0000-0000-000000000133"),
        "Ministry of Education of the PRC",
        "普通高中课程方案和课程标准（2017年版2020年修订）",
        "https://hudong.moe.gov.cn/srcsite/A26/s8001/202006/t20200603_462199.html",
        "2017-2020",
        date(2020, 5, 11),
    ),
    (
        UUID("00000000-0000-0000-0000-000000000134"),
        "Council of Europe",
        "CEFR Companion Volume",
        "https://www.coe.int/en/web/common-european-framework-reference-languages/cefr-companion-volume-and-its-language-versions",
        "2020",
        date(2020, 1, 1),
    ),
)

_PROFILES = (
    (
        UUID("00000000-0000-0000-0000-000000000141"),
        "cn-preschool-3-6-2012",
        "中国学前发展",
        "CN",
        "2012",
        _SOURCES[0][0],
    ),
    (
        UUID("00000000-0000-0000-0000-000000000142"),
        "cn-compulsory-2022",
        "中国义务教育",
        "CN",
        "2022",
        _SOURCES[1][0],
    ),
    (
        UUID("00000000-0000-0000-0000-000000000143"),
        "cn-high-school-2017-2020",
        "中国普通高中",
        "CN",
        "2017-2020",
        _SOURCES[2][0],
    ),
    (
        UUID("00000000-0000-0000-0000-000000000144"),
        "cefr-2020",
        "CEFR 语言能力",
        "international",
        "2020",
        _SOURCES[3][0],
    ),
)


def upgrade() -> None:
    op.create_table(
        "curriculum_source_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("canonical_url", sa.String(length=2000), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("editorial_note", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "curriculum_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("jurisdiction", sa.String(length=100), nullable=False),
        sa.Column("version_label", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_record_id", sa.Uuid(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["source_record_id"], ["curriculum_source_records.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_curriculum_profiles_code"),
    )
    op.create_table(
        "curriculum_grade_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("internal_level", sa.String(length=10), nullable=False),
        sa.Column("external_label", sa.String(length=200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["curriculum_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id", "internal_level", "external_label", name="uq_curriculum_grade_mapping"
        ),
    )
    op.create_table(
        "curriculum_objectives",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("grade_mapping_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=150), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("domain", sa.String(length=200), nullable=False),
        sa.Column("unit", sa.String(length=200), nullable=True),
        sa.Column("knowledge_point", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["curriculum_profiles.id"]),
        sa.ForeignKeyConstraint(["grade_mapping_id"], ["curriculum_grade_mappings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "code", name="uq_curriculum_objective_code"),
    )
    op.create_index(
        "ix_curriculum_objectives_profile_subject_domain",
        "curriculum_objectives",
        ["profile_id", "subject", "domain"],
    )
    op.create_table(
        "curriculum_objective_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("objective_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("source_locator", sa.String(length=500), nullable=False),
        sa.Column("allowed_question_types", sa.JSON(), nullable=False),
        sa.Column("difficulty_min", sa.Float(), nullable=False),
        sa.Column("difficulty_max", sa.Float(), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "difficulty_min >= 0 AND difficulty_max <= 1 AND difficulty_min <= difficulty_max",
            name="ck_curriculum_revision_difficulty_range",
        ),
        sa.ForeignKeyConstraint(["objective_id"], ["curriculum_objectives.id"]),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "objective_id", "revision_number", name="uq_curriculum_objective_revision"
        ),
    )
    op.create_table(
        "curriculum_prerequisites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("objective_revision_id", sa.Uuid(), nullable=False),
        sa.Column("prerequisite_revision_id", sa.Uuid(), nullable=False),
        sa.Column("relation_type", sa.String(length=50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "objective_revision_id <> prerequisite_revision_id",
            name="ck_curriculum_prerequisite_not_self",
        ),
        sa.ForeignKeyConstraint(["objective_revision_id"], ["curriculum_objective_revisions.id"]),
        sa.ForeignKeyConstraint(
            ["prerequisite_revision_id"], ["curriculum_objective_revisions.id"]
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "objective_revision_id", "prerequisite_revision_id", name="uq_curriculum_prerequisite"
        ),
    )
    _seed_initial_catalogue()


def downgrade() -> None:
    op.drop_table("curriculum_prerequisites")
    op.drop_table("curriculum_objective_revisions")
    op.drop_index(
        "ix_curriculum_objectives_profile_subject_domain", table_name="curriculum_objectives"
    )
    op.drop_table("curriculum_objectives")
    op.drop_table("curriculum_grade_mappings")
    op.drop_table("curriculum_profiles")
    op.drop_table("curriculum_source_records")


def _seed_initial_catalogue() -> None:
    source_table = sa.table(
        "curriculum_source_records",
        sa.column("id", sa.Uuid()),
        sa.column("issuer", sa.String()),
        sa.column("title", sa.String()),
        sa.column("canonical_url", sa.String()),
        sa.column("version_label", sa.String()),
        sa.column("published_at", sa.Date()),
        sa.column("editorial_note", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    profile_table = sa.table(
        "curriculum_profiles",
        sa.column("id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("jurisdiction", sa.String()),
        sa.column("version_label", sa.String()),
        sa.column("status", sa.String()),
        sa.column("source_record_id", sa.Uuid()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    mapping_table = sa.table(
        "curriculum_grade_mappings",
        sa.column("id", sa.Uuid()),
        sa.column("profile_id", sa.Uuid()),
        sa.column("internal_level", sa.String()),
        sa.column("external_label", sa.String()),
        sa.column("position", sa.Integer()),
    )
    objective_table = sa.table(
        "curriculum_objectives",
        sa.column("id", sa.Uuid()),
        sa.column("profile_id", sa.Uuid()),
        sa.column("grade_mapping_id", sa.Uuid()),
        sa.column("code", sa.String()),
        sa.column("subject", sa.String()),
        sa.column("domain", sa.String()),
        sa.column("knowledge_point", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    revision_table = sa.table(
        "curriculum_objective_revisions",
        sa.column("id", sa.Uuid()),
        sa.column("objective_id", sa.Uuid()),
        sa.column("revision_number", sa.Integer()),
        sa.column("text", sa.String()),
        sa.column("source_locator", sa.String()),
        sa.column("allowed_question_types", sa.JSON()),
        sa.column("difficulty_min", sa.Float()),
        sa.column("difficulty_max", sa.Float()),
        sa.column("activity_type", sa.String()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    op.bulk_insert(
        source_table,
        [
            {
                "id": item[0],
                "issuer": item[1],
                "title": item[2],
                "canonical_url": item[3],
                "version_label": item[4],
                "published_at": item[5],
                "editorial_note": "Store source metadata and short approved summaries only.",
                "created_at": now,
            }
            for item in _SOURCES
        ],
    )
    op.bulk_insert(
        profile_table,
        [
            {
                "id": item[0],
                "code": item[1],
                "name": item[2],
                "jurisdiction": item[3],
                "version_label": item[4],
                "status": "active",
                "source_record_id": item[5],
                "created_at": now,
                "updated_at": now,
            }
            for item in _PROFILES
        ],
    )
    mappings: list[dict[str, object]] = []
    sequence = 1
    for profile_id, levels in (
        (_PROFILES[0][0], ("K3_4", "K4_5", "K5_6")),
        (_PROFILES[1][0], tuple(f"G{grade}" for grade in range(1, 10))),
        (_PROFILES[2][0], ("G10", "G11", "G12")),
        (_PROFILES[3][0], tuple(f"G{grade}" for grade in range(1, 14))),
    ):
        for position, level in enumerate(levels, start=1):
            mappings.append(
                {
                    "id": UUID(f"00000000-0000-0000-0000-{sequence:012d}"),
                    "profile_id": profile_id,
                    "internal_level": level,
                    "external_label": level,
                    "position": position,
                }
            )
            sequence += 1
    op.bulk_insert(mapping_table, mappings)
    objectives = (
        (
            UUID("00000000-0000-0000-0000-000000000151"),
            _PROFILES[0][0],
            UUID("00000000-0000-0000-0000-000000000001"),
            "CN-K-NUMBER-SENSE-001",
            "early_learning",
            "number_sense",
            "one-to-one correspondence",
        ),
        (
            UUID("00000000-0000-0000-0000-000000000152"),
            _PROFILES[1][0],
            UUID("00000000-0000-0000-0000-000000000004"),
            "CN-COMP-MATH-G1-NUM-001",
            "mathematics",
            "number",
            "whole numbers",
        ),
        (
            UUID("00000000-0000-0000-0000-000000000153"),
            _PROFILES[2][0],
            UUID("00000000-0000-0000-0000-000000000013"),
            "CN-HS-MATH-G10-ALG-001",
            "mathematics",
            "algebra",
            "algebraic expressions",
        ),
        (
            UUID("00000000-0000-0000-0000-000000000154"),
            _PROFILES[3][0],
            UUID("00000000-0000-0000-0000-000000000016"),
            "CEFR-A2-READ-001",
            "english",
            "reading",
            "short familiar texts",
        ),
    )
    op.bulk_insert(
        objective_table,
        [
            {
                "id": item[0],
                "profile_id": item[1],
                "grade_mapping_id": item[2],
                "code": item[3],
                "subject": item[4],
                "domain": item[5],
                "knowledge_point": item[6],
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            for item in objectives
        ],
    )
    op.bulk_insert(
        revision_table,
        [
            {
                "id": UUID("00000000-0000-0000-0000-000000000161"),
                "objective_id": objectives[0][0],
                "revision_number": 1,
                "text": "通过实物配对探索一一对应。",
                "source_locator": "number sense",
                "allowed_question_types": ["learning_activity-v1"],
                "difficulty_min": 0.0,
                "difficulty_max": 0.2,
                "activity_type": "learning_activity",
                "status": "active",
                "created_at": now,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000162"),
                "objective_id": objectives[1][0],
                "revision_number": 1,
                "text": "在熟悉情境中比较和使用整数。",
                "source_locator": "mathematics",
                "allowed_question_types": ["M1"],
                "difficulty_min": 0.0,
                "difficulty_max": 0.4,
                "activity_type": "scored_question",
                "status": "active",
                "created_at": now,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000163"),
                "objective_id": objectives[2][0],
                "revision_number": 1,
                "text": "理解并化简基础代数表达式。",
                "source_locator": "mathematics",
                "allowed_question_types": ["M2"],
                "difficulty_min": 0.2,
                "difficulty_max": 0.7,
                "activity_type": "scored_question",
                "status": "active",
                "created_at": now,
            },
            {
                "id": UUID("00000000-0000-0000-0000-000000000164"),
                "objective_id": objectives[3][0],
                "revision_number": 1,
                "text": "阅读熟悉主题的简短文本并提取明确事实。",
                "source_locator": "A2 reading",
                "allowed_question_types": ["E1", "E2"],
                "difficulty_min": 0.2,
                "difficulty_max": 0.5,
                "activity_type": "scored_question",
                "status": "active",
                "created_at": now,
            },
        ],
    )
