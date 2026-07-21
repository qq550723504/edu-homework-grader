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
from edu_grader_api.services.question_fingerprints import fingerprint_prompt


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
