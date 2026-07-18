from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from edu_grader_api.db import Base
from edu_grader_api.models import (
    GradingPolicy,
    Question,
    QuestionTestCase,
    QuestionVersion,
    Role,
    Tenant,
    TestRunStatus as RunStatus,
    User,
    VersionStatus,
)
from edu_grader_api.services.questions import (
    PublishConflict,
    publish_question_version,
    run_question_tests,
)


@dataclass(frozen=True)
class FakeGradeResult:
    decision: str
    score: float
    evidence: dict[str, object]
    grader_version: str = "fake-grader-1"


class FakeGraderClient:
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> FakeGradeResult:
        return FakeGradeResult(**answer_json["result"])


def test_passing_complete_test_run_is_required_before_publishing() -> None:
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
        draft = QuestionVersion(
            question=question,
            version_number=1,
            status=VersionStatus.DRAFT,
            prompt="What is 2 + 3?",
            question_type="M1",
            grading_policy=policy,
            rule_json={"expected": 5},
            created_by_user=teacher,
        )
        session.add_all([tenant, teacher, policy, question, draft])
        session.flush()
        for category, decision, score in (
            ("correct", "auto_accepted", 1),
            ("incorrect", "auto_rejected", 0),
            ("empty", "auto_rejected", 0),
            ("boundary", "auto_accepted", 1),
        ):
            session.add(
                QuestionTestCase(
                    question_version=draft,
                    category=category,
                    answer_json={
                        "result": {
                            "decision": decision,
                            "score": score,
                            "evidence": {"category": category},
                        }
                    },
                    expected_decision=decision,
                    expected_score=score,
                    expected_evidence_json={"category": category},
                )
            )
        session.commit()

        with pytest.raises(PublishConflict):
            publish_question_version(session, draft, actor_user_id=teacher.id)

        run = run_question_tests(session, draft, trigger="manual", grader_client=FakeGraderClient())
        session.flush()
        published = publish_question_version(session, draft, actor_user_id=teacher.id)

        assert run.status is RunStatus.PASSED
        assert len(run.case_runs) == 4
        assert all(case_run.passed for case_run in run.case_runs)
        assert published.status is VersionStatus.PUBLISHED
