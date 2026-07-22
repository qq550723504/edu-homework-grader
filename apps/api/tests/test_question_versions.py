from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.db import Base
from edu_grader_api.models import (
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    Tenant,
    User,
    VersionStatus,
)
from edu_grader_api.services.questions import create_successor_draft, update_draft


def test_published_version_is_preserved_when_creating_a_successor_draft() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        tenant = Tenant(slug="pilot", name="Pilot School")
        teacher = User(
            tenant=tenant,
            role=Role.TEACHER,
            display_name="Teacher",
            work_email="teacher@pilot.example",
        )
        policy = GradingPolicy(question_type="M1", policy_version="1", json_schema={})
        question = Question(tenant=tenant, created_by_user=teacher, title="Addition")
        published = QuestionVersion(
            question=question,
            version_number=1,
            status=VersionStatus.PUBLISHED,
            prompt="What is 2 + 3?",
            reading_material="Read the worked example before answering.",
            question_type="M1",
            grading_policy=policy,
            rule_json={"expected": 5},
            created_by_user=teacher,
        )
        session.add_all([tenant, teacher, policy, question, published])
        session.commit()

        successor = create_successor_draft(session, published, actor_user_id=teacher.id)
        update_draft(session, successor, actor_user_id=teacher.id, prompt="What is 3 + 3?")
        session.commit()

        assert successor.version_number == 2
        assert successor.status is VersionStatus.DRAFT
        assert successor.prompt == "What is 3 + 3?"
        assert successor.reading_material == "Read the worked example before answering."
        assert published.prompt == "What is 2 + 3?"
