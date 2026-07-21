from __future__ import annotations

from decimal import Decimal, InvalidOperation
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
    GuardianConsentStatus,
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    StudentGuardianConsent,
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


class DeterministicE2EGraderClient:
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
        if question_type == "M1" and policy_version == "1":
            return self._grade_m1(rule_json, answer_json)
        if question_type == "M2" and policy_version == "2":
            return GradeResult(
                decision="correct",
                score=4.0,
                grader_version="e2e-m2@1",
                evidence=M2_EVIDENCE,
            )
        if question_type == "E1" and policy_version == "2":
            return self._grade_english_match(rule_json, answer_json, "accepted_answers")
        if question_type == "E2" and policy_version == "1":
            return self._grade_english_match(rule_json, answer_json, "accepted_forms")
        if question_type == "E3" and policy_version == "1":
            return self._grade_english_review("grammar_assistance")
        if question_type == "E4" and policy_version == "2":
            return self._grade_english_review("scoring_point_review")
        raise ValueError(f"the E2E grader does not support {question_type}@{policy_version}")

    @staticmethod
    def _grade_m1(rule_json: dict[str, object], answer_json: dict[str, object]) -> GradeResult:
        expected = rule_json.get("expected")
        text = answer_json.get("text")
        if answer_json.get("format") != "text-v1" or not isinstance(text, str):
            raise ValueError("M1 answers require a text-v1 envelope")
        if isinstance(expected, bool) or not isinstance(expected, int | float):
            raise ValueError("M1 rules require a numeric expected value")
        try:
            matched = Decimal(text.strip()) == Decimal(str(expected))
        except InvalidOperation:
            matched = False
        score = 1.0 if matched else 0.0
        return GradeResult(
            decision="auto_accepted" if matched else "auto_rejected",
            score=score,
            grader_version="e2e-m1@1",
            evidence={
                "max_score": 1.0,
                "confidence": 1.0,
                "requires_review": False,
                "criteria": [
                    {"code": "numeric_value", "passed": matched, "score": score, "max_score": 1.0}
                ],
                "feedback": [],
                "dependency_versions": {"grader": "e2e-m1@1"},
            },
        )

    @staticmethod
    def _grade_english_match(
        rule_json: dict[str, object], answer_json: dict[str, object], accepted_key: str
    ) -> GradeResult:
        accepted = rule_json.get(accepted_key)
        text = answer_json.get("text")
        if answer_json.get("format") != "text-v1" or not isinstance(text, str):
            raise ValueError("English answers require a text-v1 envelope")
        if not isinstance(accepted, list) or not all(isinstance(value, str) for value in accepted):
            raise ValueError(f"English rules require {accepted_key}")
        normalized = text.strip().casefold().rstrip(".")
        matched = bool(normalized) and normalized in {
            value.strip().casefold().rstrip(".") for value in accepted
        }
        max_score = rule_json.get("max_score", 1)
        if isinstance(max_score, bool) or not isinstance(max_score, int | float):
            raise ValueError("English rules require a numeric max_score")
        score = float(max_score) if matched else 0.0
        return GradeResult(
            decision="auto_accepted" if matched else "auto_rejected",
            score=score,
            grader_version="e2e-english@1",
            evidence={"criterion": accepted_key, "matched": matched, "max_score": float(max_score)},
        )

    @staticmethod
    def _grade_english_review(criterion: str) -> GradeResult:
        return GradeResult(
            decision="needs_review",
            score=0.0,
            grader_version="e2e-english@1",
            evidence={"criterion": criterion, "requires_review": True},
        )


DeterministicM2Client = DeterministicE2EGraderClient


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
    text_policy = GradingPolicy(
        question_type="M1",
        policy_version="1",
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
    text_question = Question(
        tenant=tenant,
        created_by_user=teacher,
        title="Explain your reasoning",
    )
    text_version = QuestionVersion(
        question=text_question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt="Explain how you simplified the expression.",
        question_type="M1",
        grading_policy=text_policy,
        rule_json={"expected": 1},
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
    draft_assignment = Assignment(
        tenant=tenant,
        classroom=classroom,
        created_by_user=teacher,
        title="Draft isolation",
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
            text_policy,
            question,
            version,
            text_question,
            text_version,
            assignment,
            draft_assignment,
        ]
    )
    session.flush()
    version.published_by_user_id = teacher.id
    text_version.published_by_user_id = teacher.id
    session.add_all(
        [
            ClassTeacher(class_id=classroom.id, teacher_id=teacher.id),
            Enrollment(class_id=classroom.id, student_id=student.id),
            StudentGuardianConsent(
                student_id=student.id,
                requires_guardian_consent=False,
                status=GuardianConsentStatus.NOT_REQUIRED,
            ),
            AssignmentItem(
                assignment_id=assignment.id,
                question_version_id=version.id,
                position=1,
            ),
            AssignmentItem(
                assignment_id=draft_assignment.id,
                question_version_id=version.id,
                position=1,
            ),
            AssignmentItem(
                assignment_id=draft_assignment.id,
                question_version_id=text_version.id,
                position=2,
            ),
        ]
    )
    session.commit()
