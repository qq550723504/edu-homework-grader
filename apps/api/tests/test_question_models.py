import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from edu_grader_api.models import (
    Base,
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    Tenant,
    User,
    VersionStatus,
)


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
