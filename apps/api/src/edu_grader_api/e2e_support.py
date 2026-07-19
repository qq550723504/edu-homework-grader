from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jwt.exceptions import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import VerifiedIdentity
from .models import (
    Assignment,
    AssignmentItem,
    AssignmentStatus,
    ClassTeacher,
    Classroom,
    Enrollment,
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    Tenant,
    User,
    VersionStatus,
)
from .services.questions import GradeResult


STUDENT_TOKEN = "e2e-student-token"
TEACHER_TOKEN = "e2e-teacher-token"
E2E_ISSUER = "http://localhost:8080/realms/edu-grader"

M2_RULE = {
    "expected": ["Add", "x", 1],
    "variables": ["x"],
    "required_form": "expanded",
    "max_score": 4,
}
M2_EVIDENCE = {
    "max_score": 4,
    "confidence": 1.0,
    "requires_review": True,
    "criteria": [
        {
            "code": "algebraic_equivalence",
            "passed": True,
            "score": 4,
            "max_score": 4,
        }
    ],
    "feedback": [{"type": "result", "message": "表达式等价。"}],
    "dependency_versions": {"grader": "e2e-m2@1"},
}


class StaticE2EVerifier:
    _identities = {
        STUDENT_TOKEN: VerifiedIdentity(
            issuer=E2E_ISSUER,
            subject="e2e-student",
            school_id="E2E-S-001",
        ),
        TEACHER_TOKEN: VerifiedIdentity(
            issuer=E2E_ISSUER,
            subject="e2e-teacher",
            school_id=None,
        ),
    }

    def verify(self, token: str) -> VerifiedIdentity:
        try:
            return self._identities[token]
        except KeyError:
            raise InvalidTokenError("invalid E2E token") from None


class DeterministicM2Client:
    def __init__(self, _: str) -> None:
        pass

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        return {"kind": "symbol", "value": "x_plus_1"}

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        if question_type != "M2" or policy_version != "2":
            raise ValueError("the E2E grader only supports M2 policy version 2")
        return GradeResult(
            decision="correct",
            score=4.0,
            grader_version="e2e-m2@1",
            evidence=M2_EVIDENCE,
        )


def seed_demo_assignment(session: Session) -> None:
    tenant = session.scalar(select(Tenant).where(Tenant.slug == "pilot"))
    if tenant is not None:
        existing_assignment = session.scalar(
            select(Assignment.id).where(
                Assignment.tenant_id == tenant.id,
                Assignment.title == "Expression equivalence",
            )
        )
        if existing_assignment is not None:
            return

    now = datetime.now(timezone.utc)
    tenant = tenant or Tenant(slug="pilot", name="E2E Pilot School")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer=E2E_ISSUER,
        oidc_subject="e2e-teacher",
        display_name="E2E Teacher",
    )
    student = User(
        tenant=tenant,
        role=Role.STUDENT,
        school_id="E2E-S-001",
        oidc_issuer=E2E_ISSUER,
        oidc_subject="e2e-student",
        display_name="E2E Student",
    )
    classroom = Classroom(
        tenant=tenant,
        code="E2E-7A",
        name="E2E Year 7 A",
    )
    policy = GradingPolicy(
        question_type="M2",
        policy_version="2",
        json_schema={},
    )
    question = Question(
        tenant=tenant,
        created_by_user=teacher,
        title="Expand x plus one",
    )
    version = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt="Write x + 1 in expanded form.",
        question_type="M2",
        grading_policy=policy,
        rule_json=M2_RULE,
        created_by_user=teacher,
        published_by_user_id=None,
        published_at=now,
    )
    assignment = Assignment(
        tenant=tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Expression equivalence",
        subject="mathematics",
        due_at=now + timedelta(days=7),
        submission_rule_json={"allow_late": False},
        status=AssignmentStatus.PUBLISHED,
        published_at=now,
    )
    session.add_all(
        [
            tenant,
            teacher,
            student,
            classroom,
            policy,
            question,
            version,
            assignment,
        ]
    )
    session.flush()
    version.published_by_user_id = teacher.id
    session.add_all(
        [
            ClassTeacher(class_id=classroom.id, teacher_id=teacher.id),
            Enrollment(class_id=classroom.id, student_id=student.id),
            AssignmentItem(
                assignment_id=assignment.id,
                question_version_id=version.id,
                position=1,
            ),
        ]
    )
    session.commit()
