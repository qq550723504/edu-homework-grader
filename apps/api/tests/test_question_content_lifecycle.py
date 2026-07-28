import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.db import Base
from edu_grader_api.models import (
    ExternalContentReference,
    QuestionMediaAsset,
    Role,
    Tenant,
    User,
    VersionStatus,
)
from edu_grader_api.services.question_content import (
    QUESTION_CONTENT_SCHEMA_VERSION,
    QuestionContentValidationError,
    legacy_projection,
    legacy_question_content,
)
from edu_grader_api.services.questions import create_question, create_successor_draft, update_draft


def test_create_and_edit_keep_the_legacy_projection_in_sync() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant, teacher = _tenant_teacher(session)
        version = create_question(
            session,
            tenant_id=tenant.id,
            actor_user_id=teacher.id,
            title="Addition",
            prompt="What is 2 + 3?",
            question_type="M1",
            policy_version="1",
            rule_json={"expected": 5},
        )
        session.flush()

        assert version.content_schema_version == QUESTION_CONTENT_SCHEMA_VERSION
        assert legacy_projection(version.content_json) == (version.prompt, None)

        content = legacy_question_content("What is 3 + 3?", "Read this first.")
        update_draft(
            session,
            version,
            actor_user_id=teacher.id,
            prompt="What is 3 + 3?",
            reading_material="Read this first.",
            content_json=content,
        )
        assert legacy_projection(version.content_json) == (
            "What is 3 + 3?",
            "Read this first.",
        )

        with pytest.raises(
            QuestionContentValidationError, match="question_content_legacy_mismatch"
        ):
            update_draft(
                session,
                version,
                actor_user_id=teacher.id,
                prompt="What is 4 + 4?",
                content_json=content,
            )


def test_successor_copies_independent_content_media_and_source_rows() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant, teacher = _tenant_teacher(session)
        published = create_question(
            session,
            tenant_id=tenant.id,
            actor_user_id=teacher.id,
            title="Addition",
            prompt="What is 2 + 3?",
            question_type="M1",
            policy_version="1",
            rule_json={"expected": 5},
        )
        session.flush()
        published.media_assets.append(
            QuestionMediaAsset(
                kind="image",
                storage_key="question-assets/example.png",
                mime_type="image/png",
                byte_size=42,
                content_hash="a" * 64,
                alt_text="Worked example",
                position=1,
            )
        )
        published.external_content_references.append(
            ExternalContentReference(
                provider="open-content",
                external_id="example-1",
                source_version="2026-07",
                content_hash="b" * 64,
                license_code="CC-BY-4.0",
                license_snapshot_json={"name": "Creative Commons Attribution 4.0"},
                tenant_scope_id=tenant.id,
                allow_persist=True,
                allow_student_display=True,
                allow_ai_processing=False,
                allow_redistribution=True,
            )
        )
        published.status = VersionStatus.PUBLISHED
        session.flush()

        successor = create_successor_draft(session, published, actor_user_id=teacher.id)
        session.flush()

        assert successor.content_json == published.content_json
        assert successor.content_json is not published.content_json
        assert successor.media_assets[0].id != published.media_assets[0].id
        assert successor.media_assets[0].storage_key == published.media_assets[0].storage_key
        assert (
            successor.external_content_references[0].id
            != published.external_content_references[0].id
        )
        assert (
            successor.external_content_references[0].license_snapshot_json
            == published.external_content_references[0].license_snapshot_json
        )


def _tenant_teacher(session: Session) -> tuple[Tenant, User]:
    tenant = Tenant(slug="pilot", name="Pilot")
    teacher = User(tenant=tenant, role=Role.TEACHER, display_name="Teacher")
    session.add_all([tenant, teacher])
    session.flush()
    return tenant, teacher
