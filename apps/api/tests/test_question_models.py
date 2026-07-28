import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Text, create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    ExternalContentReference,
    GradingPolicy,
    Question,
    QuestionMediaAsset,
    QuestionVersion,
    Role,
    Tenant,
    User,
    VersionStatus,
)
from edu_grader_api.services.question_fingerprints import fingerprint_prompt


def test_question_version_reading_material_is_nullable_unbounded_text() -> None:
    column = QuestionVersion.__table__.c.reading_material

    assert column.nullable is True
    assert isinstance(column.type, Text)


def test_question_version_has_versioned_content_snapshot() -> None:
    assert QuestionVersion.__table__.c.content_schema_version.nullable is False
    assert QuestionVersion.__table__.c.content_json.nullable is False


def test_question_content_children_preserve_versioned_source_identity() -> None:
    assert any(
        constraint.name == "uq_question_media_asset_position"
        for constraint in QuestionMediaAsset.__table__.constraints
    )
    assert any(
        constraint.name == "uq_external_content_reference_identity"
        for constraint in ExternalContentReference.__table__.constraints
    )


def _load_reading_material_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0020_question_version_reading_material.py"
    )
    spec = spec_from_file_location("migration_0020_reading_material", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _load_question_content_migration():
    migration_path = (
        Path(__file__).parents[1] / "alembic" / "versions" / "0026_question_content_snapshots.py"
    )
    spec = spec_from_file_location("migration_0026_question_content_snapshots", migration_path)
    assert spec is not None and spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_reading_material_migration_declares_expected_add_column_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_reading_material_migration()
    added: list[tuple[str, object]] = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table_name, column: added.append((table_name, column)),
    )

    migration.upgrade()

    assert migration.down_revision == "0019_ai_generated_question_reviews"
    assert len(added) == 1
    table_name, column = added[0]
    assert table_name == "question_versions"
    assert column.name == "reading_material"
    assert column.nullable is True
    assert isinstance(column.type, Text)


def test_reading_material_migration_upgrades_and_downgrades_in_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_reading_material_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE question_versions (id INTEGER PRIMARY KEY NOT NULL)"
        )
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)

        migration.upgrade()

        upgraded_columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("question_versions")
        }
        assert upgraded_columns["reading_material"]["nullable"] is True
        assert isinstance(upgraded_columns["reading_material"]["type"], Text)

        migration.downgrade()

        downgraded_columns = {
            column["name"] for column in inspect(connection).get_columns("question_versions")
        }
        assert "reading_material" not in downgraded_columns


def test_question_content_migration_backfills_legacy_versions_and_child_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _load_question_content_migration()
    engine = create_engine("sqlite+pysqlite:///:memory:")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE question_versions ("
            "id INTEGER PRIMARY KEY NOT NULL, "
            "prompt TEXT NOT NULL, "
            "reading_material TEXT"
            ")"
        )
        connection.exec_driver_sql(
            "INSERT INTO question_versions (id, prompt, reading_material) "
            "VALUES (1, 'Calculate 2 + 2', 'Read first')"
        )
        connection.exec_driver_sql("CREATE TABLE tenants (id INTEGER PRIMARY KEY NOT NULL)")
        operations = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        monkeypatch.setattr(migration, "op", operations)

        migration.upgrade()

        columns = {
            column["name"]: column
            for column in inspect(connection).get_columns("question_versions")
        }
        assert columns["content_schema_version"]["nullable"] is False
        assert columns["content_json"]["nullable"] is False
        row = connection.exec_driver_sql(
            "SELECT content_schema_version, content_json FROM question_versions WHERE id = 1"
        ).one()
        assert row.content_schema_version == "question-content-v1"
        assert json.loads(row.content_json) == {
            "stem": [{"kind": "text", "text": "Calculate 2 + 2"}],
            "reading_material": [{"kind": "text", "text": "Read first"}],
            "response": {"kind": "legacy-rule"},
            "explanation": [],
            "metadata": {"grade": None, "difficulty": None, "estimated_minutes": None},
        }
        assert {"question_media_assets", "external_content_references"} <= set(
            inspect(connection).get_table_names()
        )

        migration.downgrade()

        downgraded_columns = {
            column["name"] for column in inspect(connection).get_columns("question_versions")
        }
        assert "content_schema_version" not in downgraded_columns
        assert "content_json" not in downgraded_columns
        assert "question_media_assets" not in inspect(connection).get_table_names()
        assert "external_content_references" not in inspect(connection).get_table_names()


def test_question_version_number_is_unique_per_question() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Teacher")
        policy = GradingPolicy(
            question_type="M1",
            policy_version="1",
            json_schema={"type": "object"},
        )
        question = Question(tenant=tenant, created_by_user=teacher, title="Numeric question")
        session.add_all([tenant, teacher, policy, question])
        session.flush()
        session.add_all(
            [
                QuestionVersion(
                    question=question,
                    version_number=1,
                    status=VersionStatus.DRAFT,
                    prompt="Calculate 2 + 2",
                    question_type="M1",
                    grading_policy=policy,
                    rule_json={"expected": 4},
                    created_by_user=teacher,
                ),
                QuestionVersion(
                    question=question,
                    version_number=1,
                    status=VersionStatus.DRAFT,
                    prompt="Duplicate version",
                    question_type="M1",
                    grading_policy=policy,
                    rule_json={"expected": 4},
                    created_by_user=teacher,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            session.commit()


def test_question_version_prompt_assignment_refreshes_persisted_fingerprints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot")
        teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Teacher")
        policy = GradingPolicy(
            question_type="M1",
            policy_version="1",
            json_schema={"type": "object"},
        )
        question = Question(tenant=tenant, created_by_user=teacher, title="Numeric question")
        version = QuestionVersion(
            question=question,
            version_number=1,
            status=VersionStatus.DRAFT,
            prompt="Calculate 2 + 2",
            question_type="M1",
            grading_policy=policy,
            rule_json={"expected": 4},
            created_by_user=teacher,
        )
        session.add(version)
        session.commit()

        version.prompt = "  ＣＡＬＣＵＬＡＴＥ\t2 + 2  "
        session.commit()
        session.expire_all()

        stored = session.get(QuestionVersion, version.id)
        assert stored is not None
        expected = fingerprint_prompt("  ＣＡＬＣＵＬＡＴＥ\t2 + 2  ")
        assert stored.fingerprint_version == expected.version
        assert stored.exact_prompt_hash == expected.exact_hash
        assert stored.normalized_prompt_hash == expected.normalized_hash


def test_question_prompt_fingerprint_indexes_support_tenant_scoped_lookup() -> None:
    assert {index.name for index in Question.__table__.indexes} >= {"ix_questions_tenant_id"}
    assert {index.name for index in QuestionVersion.__table__.indexes} >= {
        "ix_question_versions_fingerprint_exact",
        "ix_question_versions_fingerprint_normalized",
    }
