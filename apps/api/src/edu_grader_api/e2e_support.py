from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
import unicodedata
from uuid import UUID

from edu_generator.providers import FakeGenerationProvider
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
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    Enrollment,
    GeneratedQuestionDraftRevision,
    GenerationJob,
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
from .services.ai_question_review import create_review_revision
from .services.generation import (
    GenerationJobRequest,
    GenerationJobSnapshot,
    create_or_get_job,
    run_generation_job,
)
from .services.grader import EmbeddingDependencyVersion, SemanticSimilarityResult
from .services.question_verification import run_candidate_verification
from .services.questions import GradeResult


STUDENT_TOKEN = "e2e-student-token"
TEACHER_TOKEN = "e2e-teacher-token"
E2E_ISSUER = "http://localhost:8080/realms/edu-grader"
AI_REVIEW_JOB_KEY = "e2e-ai-review-batch-v1"
AI_REVIEW_OBJECTIVE_REVISION_ID = UUID("00000000-0000-0000-0000-000000000037")

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

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        return SemanticSimilarityResult(
            scores=[0.0 for _ in comparisons],
            embedding=EmbeddingDependencyVersion(
                id="e2e-no-duplicates",
                revision="1",
                digest="0" * 64,
            ),
        )

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
            return self._grade_e4(rule_json, answer_json)
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
        normalization = (
            rule_json.get("normalization", {}) if accepted_key == "accepted_answers" else {}
        )
        if not isinstance(normalization, dict):
            normalization = {}
        normalized = text.strip()
        if normalization.get("ignore_terminal_punctuation", True):
            normalized = normalized.rstrip(".!?。！？").rstrip()
        if normalization.get("ignore_case", True):
            normalized = normalized.casefold()
        matched = bool(normalized) and normalized in {
            (
                value.strip().rstrip(".!?。！？").rstrip()
                if normalization.get("ignore_terminal_punctuation", True)
                else value.strip()
            ).casefold()
            if normalization.get("ignore_case", True)
            else (
                value.strip().rstrip(".!?。！？").rstrip()
                if normalization.get("ignore_terminal_punctuation", True)
                else value.strip()
            )
            for value in accepted
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

    @staticmethod
    def _grade_e4(rule_json: dict[str, object], answer_json: dict[str, object]) -> GradeResult:
        text = answer_json.get("text")
        points = rule_json.get("scoring_points")
        if answer_json.get("format") != "text-v1" or not isinstance(text, str):
            raise ValueError("English answers require a text-v1 envelope")
        if not isinstance(points, list):
            raise ValueError("E4 rules require scoring_points")
        max_score = rule_json.get("max_score", 1)
        if isinstance(max_score, bool) or not isinstance(max_score, int | float):
            raise ValueError("E4 rules require a numeric max_score")
        normalized_answer = DeterministicE2EGraderClient._normalize_english_text(text)
        criteria: list[dict[str, object]] = []
        score = 0.0
        for point in points:
            if not isinstance(point, dict):
                raise ValueError("E4 scoring points must be objects")
            point_id = point.get("id")
            phrases = point.get("evidence_phrases")
            point_score = point.get("score")
            if (
                not isinstance(point_id, str)
                or not isinstance(phrases, list)
                or isinstance(point_score, bool)
                or not isinstance(point_score, int | float)
            ):
                raise ValueError("E4 scoring points require id, evidence_phrases, and score")
            matched = any(
                (normalized_phrase := DeterministicE2EGraderClient._normalize_english_text(phrase))
                and normalized_phrase in normalized_answer
                for phrase in phrases
                if isinstance(phrase, str)
            )
            awarded = float(point_score) if matched else 0.0
            score += awarded
            criteria.append(
                {
                    "code": point_id,
                    "passed": matched,
                    "score": awarded,
                    "max_score": float(point_score),
                }
            )
        return GradeResult(
            decision="needs_review",
            score=score,
            grader_version="e2e-english@1",
            evidence={
                "criterion": "scoring_point_review",
                "requires_review": True,
                "max_score": float(max_score),
                "criteria": criteria,
            },
        )

    @staticmethod
    def _normalize_english_text(value: str) -> str:
        normalized = " ".join(unicodedata.normalize("NFKC", value).strip().split())
        return normalized.rstrip(".!?。！？").rstrip().casefold()


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
            teacher = session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.oidc_issuer == E2E_ISSUER,
                    User.oidc_subject == "e2e-teacher",
                )
            )
            if teacher is None:
                raise RuntimeError("E2E teacher is missing")
            _seed_ai_review_batch(session, tenant=tenant, teacher=teacher)
            session.commit()
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
    _seed_ai_review_batch(session, tenant=tenant, teacher=teacher)
    session.commit()


def _seed_ai_review_batch(session: Session, *, tenant: Tenant, teacher: User) -> None:
    existing_job = session.scalar(
        select(GenerationJob.id).where(
            GenerationJob.tenant_id == tenant.id,
            GenerationJob.idempotency_key == AI_REVIEW_JOB_KEY,
        )
    )
    if existing_job is not None:
        return

    revision = session.get(CurriculumObjectiveRevision, AI_REVIEW_OBJECTIVE_REVISION_ID)
    if revision is None:
        source = CurriculumSourceRecord(
            issuer="E2E Curriculum Board",
            title="E2E AI review curriculum",
            canonical_url="https://example.test/e2e-ai-review-curriculum",
            version_label="2026",
        )
        profile = CurriculumProfile(
            code="e2e-ai-review-math-2026",
            name="E2E AI Review Mathematics",
            jurisdiction="e2e",
            version_label="2026",
            status=CurriculumProfileStatus.ACTIVE,
            source_record=source,
        )
        grade = CurriculumGradeMapping(
            profile=profile,
            internal_level="G5",
            external_label="Grade 5",
            position=5,
        )
        objective = CurriculumObjective(
            profile=profile,
            grade_mapping=grade,
            code="E2E-AI-REVIEW-M1",
            subject="mathematics",
            domain="number",
            knowledge_point="whole-number practice",
            status=CurriculumProfileStatus.ACTIVE,
        )
        revision = CurriculumObjectiveRevision(
            id=AI_REVIEW_OBJECTIVE_REVISION_ID,
            objective=objective,
            revision_number=1,
            text="Solve whole-number practice items.",
            source_locator="e2e fixture",
            allowed_question_types=["M1"],
            difficulty_min=0,
            difficulty_max=1,
            activity_type=CurriculumActivityType.SCORED_QUESTION,
            status=CurriculumRevisionStatus.ACTIVE,
        )
        session.add(revision)
        session.flush()

    job = create_or_get_job(
        session,
        request=GenerationJobRequest(
            curriculum_objective_revision_id=revision.id,
            question_types=["M1", "M1"],
            requested_count=2,
            idempotency_key=AI_REVIEW_JOB_KEY,
        ),
        actor=teacher,
        snapshot=GenerationJobSnapshot(
            grade="Grade 5",
            subject="E2E AI review batch",
            policy_catalog_version="2026.07",
            prompt_version="generator-v1",
        ),
    )
    run_generation_job(session, job=job, provider=FakeGenerationProvider(seed=0))

    drafts = sorted(job.drafts, key=lambda draft: draft.ordinal)
    if len(drafts) != 2:
        raise RuntimeError("E2E AI review batch did not create two candidates")

    blocked_candidate = deepcopy(drafts[0].current_revision.candidate_json)
    blocked_candidate["rule_json"] = {"expected": "six"}
    create_review_revision(
        session,
        drafts[0],
        teacher,
        1,
        blocked_candidate,
        DeterministicE2EGraderClient("unused"),
        idempotency_key="e2e-ai-review-blocked-revision-v1",
        request_digest="e2e-ai-review-blocked-revision-v1",
    )

    second_revision = session.scalar(
        select(GeneratedQuestionDraftRevision).where(
            GeneratedQuestionDraftRevision.id == drafts[1].current_revision_id,
            GeneratedQuestionDraftRevision.generated_question_draft_id == drafts[1].id,
        )
    )
    if second_revision is None:
        raise RuntimeError("E2E AI review candidate revision is missing")
    run_candidate_verification(
        session,
        draft=drafts[1],
        revision=second_revision,
        grader_client=DeterministicE2EGraderClient("unused"),
    )
