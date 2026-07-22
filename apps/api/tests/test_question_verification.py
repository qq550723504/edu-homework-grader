import importlib.util
from decimal import Decimal
from uuid import uuid4

import pytest
from edu_grader.mathjson import normalize_mathjson
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from edu_grader_api.e2e_support import DeterministicE2EGraderClient
from edu_grader_api.models import (
    Base,
    CurriculumActivityType,
    CurriculumGradeMapping,
    CurriculumObjective,
    CurriculumObjectiveRevision,
    CurriculumProfile,
    CurriculumProfileStatus,
    CurriculumRevisionStatus,
    CurriculumSourceRecord,
    GenerationAttempt,
    GenerationJob,
    GenerationJobStatus,
    GenerationValidationRun,
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GradingPolicy,
    Question,
    QuestionVersion,
    Role,
    Tenant,
    User,
    ValidationRunStatus,
    VersionStatus,
)
from edu_grader_api.services.questions import GradeResult
from edu_grader_api.services.grader import (
    EmbeddingDependencyVersion,
    SemanticSimilarityResult,
)
from edu_grader_api.services.question_fingerprints import fingerprint_prompt
import edu_grader_api.services.question_verification as verification


DEFAULT_EMBEDDING = EmbeddingDependencyVersion(
    id="local-model",
    revision="test-revision",
    digest="sha256:test",
)


def semantic_result(
    scores: list[object],
    embedding: EmbeddingDependencyVersion = DEFAULT_EMBEDDING,
) -> SemanticSimilarityResult:
    return SemanticSimilarityResult(scores=scores, embedding=embedding)  # type: ignore[arg-type]


def test_question_verification_service_module_exists() -> None:
    assert importlib.util.find_spec("edu_grader_api.services.question_verification") is not None


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class PassingGrader:
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        if question_type == "M1":
            text = answer_json.get("text")
            expected = rule_json.get("expected")
            tolerance = rule_json.get("tolerance", 0)
            if (
                not isinstance(text, str)
                or not isinstance(expected, int | float)
                or not isinstance(tolerance, int | float)
            ):
                return GradeResult("auto_rejected", 0, {}, "fake-grader-v1")
            try:
                accepted = bool(text) and abs(float(text) - expected) <= tolerance
            except ValueError:
                accepted = False
            return GradeResult(
                "auto_accepted" if accepted else "auto_rejected",
                1 if accepted else 0,
                {"probe": "accepted" if accepted else "rejected"},
                "fake-grader-v1",
            )
        return GradeResult(
            decision="auto_accepted",
            score=1,
            evidence={"probe": "accepted"},
            grader_version="fake-grader-v1",
        )

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        return semantic_result([0.0] * len(comparisons))


class SemanticGrader(PassingGrader):
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.semantic_requests: list[tuple[str, list[str]]] = []

    def semantic_similarity(self, query: str, comparisons: list[str]) -> SemanticSimilarityResult:
        self.semantic_requests.append((query, comparisons))
        if not self.responses:
            raise RuntimeError("unexpected semantic similarity call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, SemanticSimilarityResult):
            return response
        return semantic_result(response)  # type: ignore[arg-type]


class MissingSemanticGrader:
    grade = PassingGrader.grade


class FailingGrader(PassingGrader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise RuntimeError("grader is unavailable")


class RecordingM1Grader(PassingGrader):
    def __init__(self, responses: dict[str, object] | None = None) -> None:
        self.responses = responses or {}
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        text = answer_json["text"]
        assert isinstance(text, str)
        if text in self.responses:
            response = self.responses[text]
            if isinstance(response, Exception):
                raise response
            return response  # type: ignore[return-value]
        return super().grade(question_type, rule_json, answer_json, policy_version=policy_version)


class ExplosiveM1Score(int):
    def __gt__(self, other: object) -> bool:
        raise RuntimeError("numeric comparison secret")

    def __eq__(self, other: object) -> bool:
        raise RuntimeError("numeric comparison secret")


class M1ResultWithoutDecision:
    score = 1


class PassingE2Grader(PassingGrader):
    def __init__(self) -> None:
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        return GradeResult("auto_accepted", 1, {}, "fake-e2-v1")


class FailingE2Grader(PassingE2Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise RuntimeError("English grader diagnostic")


class PartialE2Grader(PassingE2Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("auto_accepted", 0.5, {}, "fake-e2-v1")


def valid_e2_candidate() -> dict[str, object]:
    return {
        "question_type": "E2",
        "policy_version": "1",
        "prompt": "Use the past tense of go.",
        "rule_json": {"lemma": "go", "accepted_forms": ["went"], "constraints": {"tense": "past"}},
        "explanation": "The past-tense form of go is went.",
    }


class PassingE3Grader(PassingGrader):
    def __init__(self, feedback: list[object] | None = None) -> None:
        self.feedback = feedback or []
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        return GradeResult("needs_review", 0, {"feedback": self.feedback}, "fake-e3-v1")


class FailingE3Grader(PassingE3Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise RuntimeError("LanguageTool diagnostic")


class UnexpectedE3DecisionGrader(PassingE3Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("auto_accepted", 1, {"feedback": []}, "fake-e3-v1")


class MalformedE3FeedbackGrader(PassingE3Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("needs_review", 0, {"feedback": ["not-an-object"]}, "fake-e3-v1")


class DependencyE3Grader(PassingE3Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult(
            "needs_review",
            0,
            {"feedback": [{"type": "dependency", "message": "LanguageTool is unavailable."}]},
            "fake-e3-v1",
        )


def valid_e3_candidate() -> dict[str, object]:
    return {
        "question_type": "E3",
        "policy_version": "1",
        "prompt": "Write one sentence about a trip.",
        "rule_json": {
            "grammar_feedback_required": False,
            "accepted_answers": ["I went to the park.", "We travelled by train."],
        },
        "explanation": "Use a complete sentence.",
    }


class PassingE4Grader(PassingGrader):
    def __init__(self) -> None:
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        point = rule_json["scoring_points"][0]  # type: ignore[index]
        return GradeResult("needs_review", point["score"], {}, "fake-e4-v1")  # type: ignore[index]


class FailingE4Grader(PassingE4Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise RuntimeError("similarity dependency diagnostic")


class UnexpectedE4DecisionGrader(PassingE4Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("auto_accepted", 2, {}, "fake-e4-v1")


class PartialE4Grader(PassingE4Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("needs_review", 0, {}, "fake-e4-v1")


class NonFiniteE4Grader(PassingE4Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult("needs_review", float("nan"), {}, "fake-e4-v1")


def valid_e4_candidate() -> dict[str, object]:
    return {
        "question_type": "E4",
        "policy_version": "2",
        "prompt": "Read the short passage and answer in one sentence.",
        "reading_material": "Because the bridge was closed, they arrived late.",
        "rule_json": {
            "max_score": 3,
            "scoring_points": [
                {
                    "id": "reason",
                    "evidence_phrases": ["because the bridge was closed"],
                    "score": 2,
                },
                {
                    "id": "result",
                    "evidence_phrases": ["they arrived late"],
                    "score": 1,
                },
            ],
        },
        "explanation": "Identify both the cause and the result.",
    }


class PassingM2Grader:
    def __init__(
        self,
        *,
        failing_probe_index: int | None = None,
        failure_kind: str | None = None,
        offset_decision: str = "auto_rejected",
    ) -> None:
        self.normalization_requests: list[dict[str, object]] = []
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []
        self.failing_probe_index = failing_probe_index
        self.failure_kind = failure_kind
        self.offset_decision = offset_decision

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        return {
            "type": "add",
            "args": [
                {"type": "symbol", "name": "x"},
                {"type": "number", "value": "1"},
            ],
        }

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        probe_index = len(self.grade_requests) - 1
        if probe_index == self.failing_probe_index:
            if self.failure_kind == "exception":
                raise RuntimeError("grader diagnostic with raw MathJSON")
            if self.failure_kind == "unexpected_decision":
                return GradeResult("unexpected", 0, {"secret": "raw MathJSON"}, "fake-m2-v1")
            if self.failure_kind == "non_finite_score":
                return GradeResult(
                    "auto_accepted" if probe_index == 0 else "needs_review",
                    float("nan"),
                    {"secret": "raw MathJSON"},
                    "fake-m2-v1",
                )
            if self.failure_kind == "wrong_nonzero_score":
                return GradeResult(
                    "auto_accepted" if probe_index == 0 else "needs_review",
                    1,
                    {"secret": "raw MathJSON"},
                    "fake-m2-v1",
                )
            raise AssertionError(f"unknown failure kind: {self.failure_kind}")
        if probe_index == 0:
            return GradeResult(
                decision="auto_accepted",
                score=float(rule_json.get("max_score", 1)),
                evidence={"probe": "accepted"},
                grader_version="fake-m2-v1",
            )
        if probe_index == 1:
            return GradeResult(self.offset_decision, 0, {}, "fake-m2-v1")
        return GradeResult("needs_review", 0, {}, "fake-m2-v1")


class FailingM2Normalizer(PassingM2Grader):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("unsafe expression diagnostic")


class FailingM2Grader(PassingM2Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        raise RuntimeError("grader diagnostic")


class PartialM2Grader(PassingM2Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        return GradeResult(
            decision="auto_accepted",
            score=3,
            evidence={},
            grader_version="fake-m2-v1",
        )


class FloatingPointM2Grader(PassingM2Grader):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        if len(self.grade_requests) == 1:
            return GradeResult(
                decision="auto_accepted",
                score=0.9 - 0.2 + 0.2,
                evidence={},
                grader_version="fake-m2-v1",
            )
        if len(self.grade_requests) == 2:
            return GradeResult("auto_rejected", 0, {}, "fake-m2-v1")
        return GradeResult("needs_review", 0, {}, "fake-m2-v1")


class ComplexM2Grader(PassingM2Grader):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        return {
            "type": "add",
            "args": [
                {"type": "symbol", "name": "x"},
                {
                    "type": "mul",
                    "args": [
                        {"type": "number", "value": "2"},
                        {"type": "symbol", "name": "x"},
                    ],
                },
            ],
        }


class InvalidSafeAstM2Grader(PassingM2Grader):
    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        return {"kind": "expression", "value": "x_plus_1"}


class SafeAstM2Grader(PassingM2Grader):
    def __init__(self, ast: dict[str, object]) -> None:
        super().__init__()
        self.ast = ast

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        return self.ast


def valid_m2_candidate() -> dict[str, object]:
    return {
        "question_type": "M2",
        "policy_version": "2",
        "prompt": "Write x + 1 in expanded form.",
        "rule_json": {
            "expected": ["Add", "x", 1],
            "variables": ["x"],
            "required_form": "expanded",
            "max_score": 4,
        },
        "explanation": "The expression is already expanded.",
    }


def _nested_negate_probe(*, depth: int) -> object:
    probe: object = 1
    for _ in range(depth):
        probe = ["Negate", probe]
    return probe


def complex_m2_candidate() -> dict[str, object]:
    candidate = valid_m2_candidate()
    candidate["rule_json"] = {
        **candidate["rule_json"],
        "expected": ["Add", "x", ["Multiply", 2, "x"]],
    }
    return candidate


def generation_draft(
    session: Session,
    *,
    candidate_json: dict[str, object] | None = None,
    allowed_question_types: list[str] | None = None,
    revision_status: CurriculumRevisionStatus = CurriculumRevisionStatus.ACTIVE,
    ordinal: int = 1,
) -> GeneratedQuestionDraft:
    tenant = Tenant(slug=f"pilot-{uuid4()}", name="Pilot")
    teacher = User(
        tenant=tenant,
        role=Role.TEACHER,
        oidc_issuer="https://issuer.example.test",
        oidc_subject=str(uuid4()),
        display_name="Teacher",
        work_email=f"teacher-{uuid4()}@example.test",
    )
    source = CurriculumSourceRecord(
        issuer="Example Board",
        title="Math curriculum",
        canonical_url="https://curriculum.example.test/math",
        version_label="2026",
    )
    profile = CurriculumProfile(
        code=f"pilot-math-{uuid4()}",
        name="Pilot Mathematics",
        jurisdiction="pilot",
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
        code=f"MATH-G5-{uuid4()}",
        subject="mathematics",
        domain="number",
        status=CurriculumProfileStatus.ACTIVE,
    )
    revision = CurriculumObjectiveRevision(
        objective=objective,
        revision_number=1,
        text="Use whole numbers under 100.",
        source_locator="section 1",
        allowed_question_types=allowed_question_types or ["M1", "E1"],
        difficulty_min=0,
        difficulty_max=1,
        activity_type=CurriculumActivityType.SCORED_QUESTION,
        status=revision_status,
    )
    session.add_all([teacher, revision])
    session.flush()
    job = GenerationJob(
        tenant_id=tenant.id,
        teacher_user_id=teacher.id,
        curriculum_profile_id=profile.id,
        curriculum_objective_revision_id=revision.id,
        grade="Grade 5",
        subject="mathematics",
        distribution_json={"question_types": ["M1", "E1"]},
        idempotency_key=str(uuid4()),
        status=GenerationJobStatus.READY_FOR_REVIEW,
        requested_count=2,
    )
    session.add(job)
    session.flush()
    attempt = GenerationAttempt(
        job_id=job.id,
        attempt_number=1,
        provider_name="fake",
        model_version="fake-v1",
        prompt_version="generator-v1",
        status="succeeded",
    )
    session.add(attempt)
    session.flush()
    candidate_content = candidate_json or {
        "objective_revision_id": str(revision.id),
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "What is 2 + 2?",
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the two whole numbers.",
        "knowledge_point": "whole-number addition",
        "difficulty": 0.2,
    }
    candidate_content.setdefault("objective_revision_id", str(revision.id))
    candidate_content.setdefault("difficulty", 0.2)
    draft = GeneratedQuestionDraft(
        job_id=job.id,
        generation_attempt_id=attempt.id,
        ordinal=ordinal,
        content_hash=f"{ordinal:x}" * 64,
        candidate_json=candidate_content,
        teacher_state="pending_review",
    )
    session.add(draft)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=draft.current_revision_id,
            generated_question_draft_id=draft.id,
            revision_number=1,
            candidate_json=candidate_content,
            content_hash=draft.content_hash,
        )
    )
    session.flush()
    return draft


def current_review_revision(
    session: Session, draft: GeneratedQuestionDraft
) -> GeneratedQuestionDraftRevision:
    revision = session.get(GeneratedQuestionDraftRevision, draft.current_revision_id)
    assert revision is not None
    return revision


def verify_current_revision(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    grader_client: object,
) -> GenerationValidationRun:
    return verification.run_candidate_verification(
        session,
        draft=draft,
        revision=current_review_revision(session, draft),
        grader_client=grader_client,
    )


def create_edited_revision(
    session: Session,
    *,
    draft: GeneratedQuestionDraft | None = None,
    prompt: str,
) -> tuple[GeneratedQuestionDraft, GeneratedQuestionDraftRevision]:
    target_draft = draft or generation_draft(session)
    revision = GeneratedQuestionDraftRevision(
        generated_question_draft_id=target_draft.id,
        revision_number=2,
        candidate_json={**target_draft.candidate_json, "prompt": prompt},
        content_hash="2" * 64,
    )
    session.add(revision)
    session.flush()
    target_draft.current_revision_id = revision.id
    session.flush()
    return target_draft, revision


def configure_grade_complexity_rules(
    session: Session, draft: GeneratedQuestionDraft, rules: object
) -> None:
    job = session.get(GenerationJob, draft.job_id)
    assert job is not None
    job.curriculum_objective_revision.objective.grade_mapping.complexity_rules_json = rules  # type: ignore[assignment]
    session.flush()


def add_batch_draft(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    prompt: str,
    ordinal: int,
) -> GeneratedQuestionDraft:
    comparison = GeneratedQuestionDraft(
        job_id=draft.job_id,
        generation_attempt_id=draft.generation_attempt_id,
        ordinal=ordinal,
        content_hash=f"{ordinal:064x}"[-64:],
        candidate_json={**draft.candidate_json, "prompt": prompt},
        teacher_state="pending_review",
    )
    session.add(comparison)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=comparison.current_revision_id,
            generated_question_draft_id=comparison.id,
            revision_number=1,
            candidate_json=comparison.candidate_json,
            content_hash=comparison.content_hash,
        )
    )
    session.flush()
    return comparison


def add_published_question(
    session: Session,
    *,
    draft: GeneratedQuestionDraft,
    prompt: str,
    tenant: Tenant | None = None,
) -> QuestionVersion:
    target_tenant = tenant or draft.job.tenant
    policy = session.scalar(
        select(GradingPolicy).where(
            GradingPolicy.question_type == "M1", GradingPolicy.policy_version == "1"
        )
    )
    if policy is None:
        policy = GradingPolicy(question_type="M1", policy_version="1", json_schema={})
    if target_tenant.id == draft.job.tenant_id:
        teacher = draft.job.teacher
    else:
        teacher = User(
            tenant=target_tenant,
            role=Role.TEACHER,
            oidc_issuer="https://issuer.example.test",
            oidc_subject=str(uuid4()),
            display_name="Other Teacher",
            work_email=f"other-teacher-{uuid4()}@example.test",
        )
    question = Question(tenant=target_tenant, created_by_user=teacher, title="Published question")
    version = QuestionVersion(
        question=question,
        version_number=1,
        status=VersionStatus.PUBLISHED,
        prompt=prompt,
        question_type="M1",
        grading_policy=policy,
        rule_json={"expected": 4},
        created_by_user=teacher,
    )
    session.add_all([teacher, policy, question, version])
    session.flush()
    return version


def finding_codes(run: object) -> set[str]:
    return {finding.code for finding in run.findings}  # type: ignore[attr-defined]


def finding_by_code(run: object, code: str) -> object:
    return next(finding for finding in run.findings if finding.code == code)  # type: ignore[attr-defined]


def valid_m1_candidate(prompt: str) -> dict[str, object]:
    return {
        "question_type": "M1",
        "policy_version": "1",
        "prompt": prompt,
        "rule_json": {"expected": 4, "tolerance": 0},
        "explanation": "Add the two whole numbers.",
        "knowledge_point": "whole-number addition",
    }


def test_validation_uses_selected_revision_not_provider_original(session: Session) -> None:
    draft, revision = create_edited_revision(session, prompt="What is 9 + 9?")
    add_published_question(session, draft=draft, prompt="Name the capital of France.")
    grader = SemanticGrader([[0.1]])

    run = verification.run_candidate_verification(
        session,
        draft=draft,
        revision=revision,
        grader_client=grader,
    )

    expected = fingerprint_prompt("What is 9 + 9?")
    assert run.draft_revision_id == revision.id
    assert grader.semantic_requests[0][0] == "What is 9 + 9?"
    assert run.feature_summary_json["candidate_prompt_fingerprint"] == {
        "version": expected.version,
        "exact_hash": expected.exact_hash,
        "normalized_hash": expected.normalized_hash,
    }


def test_batch_duplicate_uses_peer_current_revision_not_provider_original(
    session: Session,
) -> None:
    draft = generation_draft(session)
    peer = add_batch_draft(session, draft=draft, prompt="What is 3 + 3?", ordinal=2)
    create_edited_revision(session, draft=peer, prompt="What is 2 + 2?")

    run = verify_current_revision(session, draft=draft, grader_client=SemanticGrader([]))

    finding = finding_by_code(run, "duplicate_exact_prompt")
    assert finding.evidence_json == {"comparison": "batch_candidate", "method": "exact_hash"}


def test_exact_batch_duplicate_is_blocked_without_source_text(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(session, draft=draft, prompt="What is 2 + 2?", ordinal=2)
    grader = SemanticGrader([])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_exact_prompt")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"comparison": "batch_candidate", "method": "exact_hash"}
    assert finding.severity.value == "blocked"
    assert grader.semantic_requests == []


def test_normalized_batch_duplicate_is_blocked_without_source_text(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(session, draft=draft, prompt="  ＷＨＡＴ   IS 2 + 2?  ", ordinal=2)
    grader = SemanticGrader([])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_normalized_prompt")
    assert finding.evidence_json == {
        "comparison": "batch_candidate",
        "method": "normalized_hash",
    }
    assert grader.semantic_requests == []


def test_semantic_published_question_is_blocked_without_raw_comparator(
    session: Session,
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="What is 2 + 2?")
    grader = SemanticGrader([[0.96]])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_near_match")
    assert finding.evidence_json == {
        "comparison": "published_question",
        "method": "semantic",
        "threshold_band": "at_or_above",
    }
    assert "What is 2 + 2?" not in str(finding.evidence_json)
    assert {
        key: value for key, value in run.feature_summary_json.items() if key != "difficulty_signal"
    } == {
        "finding_count": len(run.findings),
        "content_policy_version": "minor-content-policy-v1",
        "fingerprint_version": "question-fingerprint-v1",
        "candidate_prompt_fingerprint": {
            "version": "question-fingerprint-v1",
            "exact_hash": fingerprint_prompt("Calculate two plus two.").exact_hash,
            "normalized_hash": fingerprint_prompt("Calculate two plus two.").normalized_hash,
        },
        "similarity_threshold": 0.92,
        "comparison_counts": {"published_question": 1, "batch_candidate": 0},
        "embedding_dependency": {
            "id": "local-model",
            "revision": "test-revision",
            "digest": "sha256:test",
        },
    }
    assert run.feature_summary_json[
        "difficulty_signal"
    ] == verification._rule_based_difficulty_signal(
        target_difficulty=0.2,
        curriculum_range=(0, 1),
        prompt="Calculate two plus two.",
        question_type="M1",
        rule_json={"expected": 4, "tolerance": 0},
        normalized_m2_ast=None,
    )


def test_semantic_same_batch_candidate_is_blocked(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(
        session,
        draft=draft,
        prompt="Calculate the sum of two and two.",
        ordinal=2,
    )

    run = verify_current_revision(session, draft=draft, grader_client=SemanticGrader([[0.92]]))

    finding = finding_by_code(run, "duplicate_semantic_near_match")
    assert finding.evidence_json == {
        "comparison": "batch_candidate",
        "method": "semantic",
        "threshold_band": "at_or_above",
    }


def test_cross_tenant_published_questions_are_never_queried(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="What is the sum of two and two?")
    other_tenant = Tenant(slug=f"other-{uuid4()}", name="Other")
    session.add(other_tenant)
    session.flush()
    add_published_question(
        session,
        draft=draft,
        tenant=other_tenant,
        prompt="Private prompt from another tenant",
    )
    grader = SemanticGrader([[0.1]])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert not finding_codes(run) & {
        "duplicate_exact_prompt",
        "duplicate_normalized_prompt",
        "duplicate_semantic_near_match",
        "duplicate_semantic_check_unavailable",
    }
    assert grader.semantic_requests == [
        ("Calculate two plus two.", ["What is the sum of two and two?"])
    ]
    assert run.feature_summary_json["comparison_counts"] == {
        "published_question": 1,
        "batch_candidate": 0,
    }


def test_duplicate_feature_summary_uses_the_gate_snapshot(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="Name the capital of France.")
    monkeypatch.setattr(verification.settings, "ai_duplicate_similarity_threshold", 0.92)

    class MutatingSemanticGrader(PassingGrader):
        def semantic_similarity(
            self, query: str, comparisons: list[str]
        ) -> SemanticSimilarityResult:
            verification.settings.ai_duplicate_similarity_threshold = 0.5
            add_batch_draft(
                session,
                draft=draft,
                prompt="Added after the comparison snapshot",
                ordinal=2,
            )
            return semantic_result([0.1])

    run = verify_current_revision(session, draft=draft, grader_client=MutatingSemanticGrader())

    assert run.status is ValidationRunStatus.PASSED
    assert {
        key: value for key, value in run.feature_summary_json.items() if key != "difficulty_signal"
    } == {
        "finding_count": 0,
        "content_policy_version": "minor-content-policy-v1",
        "fingerprint_version": "question-fingerprint-v1",
        "candidate_prompt_fingerprint": {
            "version": "question-fingerprint-v1",
            "exact_hash": fingerprint_prompt("Calculate two plus two.").exact_hash,
            "normalized_hash": fingerprint_prompt("Calculate two plus two.").normalized_hash,
        },
        "similarity_threshold": 0.92,
        "comparison_counts": {"published_question": 1, "batch_candidate": 0},
        "embedding_dependency": {
            "id": "local-model",
            "revision": "test-revision",
            "digest": "sha256:test",
        },
    }
    assert run.feature_summary_json[
        "difficulty_signal"
    ] == verification._rule_based_difficulty_signal(
        target_difficulty=0.2,
        curriculum_range=(0, 1),
        prompt="Calculate two plus two.",
        question_type="M1",
        rule_json={"expected": 4, "tolerance": 0},
        normalized_m2_ast=None,
    )


def test_normalized_comparators_are_deduplicated_across_sources_with_published_precedence(
    session: Session,
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="Name the capital of France.")
    add_batch_draft(
        session,
        draft=draft,
        prompt="  ＮＡＭＥ   THE CAPITAL OF FRANCE.  ",
        ordinal=2,
    )
    grader = SemanticGrader([[0.96]])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_near_match")
    assert grader.semantic_requests == [
        ("Calculate two plus two.", ["Name the capital of France."])
    ]
    assert finding.evidence_json == {
        "comparison": "published_question",
        "method": "semantic",
        "threshold_band": "at_or_above",
    }
    assert run.feature_summary_json["comparison_counts"] == {
        "published_question": 1,
        "batch_candidate": 0,
    }


def test_semantic_comparators_are_deduplicated_before_chunking(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    for ordinal in range(2, 131):
        add_batch_draft(
            session,
            draft=draft,
            prompt=f"Distinct comparison prompt {ordinal}",
            ordinal=ordinal,
        )
    add_batch_draft(
        session,
        draft=draft,
        prompt="  DISTINCT   COMPARISON PROMPT 2  ",
        ordinal=131,
    )
    grader = SemanticGrader([[0.1] * 128, [0.1]])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert [len(comparisons) for _, comparisons in grader.semantic_requests] == [128, 1]
    assert run.feature_summary_json["comparison_counts"] == {
        "published_question": 0,
        "batch_candidate": 129,
    }


def test_distinct_candidate_passes_duplicate_gate(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="Name the capital of France.")

    run = verify_current_revision(session, draft=draft, grader_client=SemanticGrader([[0.14]]))

    assert run.status is ValidationRunStatus.PASSED
    assert not finding_codes(run) & {
        "duplicate_exact_prompt",
        "duplicate_normalized_prompt",
        "duplicate_semantic_near_match",
        "duplicate_semantic_check_unavailable",
    }


def test_missing_semantic_client_blocks_without_diagnostics(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="What is 2 + 2?")

    run = verify_current_revision(session, draft=draft, grader_client=MissingSemanticGrader())

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert "What is 2 + 2?" not in str(finding.evidence_json)


@pytest.mark.parametrize(
    "scores",
    [
        [],
        [0.1, 0.2],
        [float("nan")],
        [True],
        [-0.01],
        [1.01],
    ],
)
def test_malformed_semantic_scores_fail_closed(session: Session, scores: list[object]) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="What is 2 + 2?")

    run = verify_current_revision(session, draft=draft, grader_client=SemanticGrader([scores]))

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert finding.evidence_json == {"category": "similarity_unavailable"}


def test_multi_chunk_semantic_failure_fails_closed(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    for ordinal in range(2, 131):
        add_batch_draft(
            session,
            draft=draft,
            prompt=f"Distinct comparison prompt {ordinal}",
            ordinal=ordinal,
        )
    grader = SemanticGrader([[0.1] * 128, RuntimeError("private dependency diagnostic")])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert [len(comparisons) for _, comparisons in grader.semantic_requests] == [128, 1]
    assert "private" not in finding.remediation


def test_later_chunk_failure_overrides_an_earlier_above_threshold_match(
    session: Session,
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    for ordinal in range(2, 131):
        add_batch_draft(
            session,
            draft=draft,
            prompt=f"Distinct comparison prompt {ordinal}",
            ordinal=ordinal,
        )
    grader = SemanticGrader([[0.99, *([0.1] * 127)], RuntimeError("private dependency diagnostic")])

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert "duplicate_semantic_near_match" not in finding_codes(run)
    assert [len(comparisons) for _, comparisons in grader.semantic_requests] == [128, 1]


def test_semantic_embedding_metadata_mismatch_across_chunks_fails_closed(
    session: Session,
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    for ordinal in range(2, 131):
        add_batch_draft(
            session,
            draft=draft,
            prompt=f"Distinct comparison prompt {ordinal}",
            ordinal=ordinal,
        )
    grader = SemanticGrader(
        [
            semantic_result([0.1] * 128),
            semantic_result(
                [0.1],
                EmbeddingDependencyVersion(
                    id="local-model",
                    revision="different-revision",
                    digest="sha256:test",
                ),
            ),
        ]
    )

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert run.feature_summary_json["embedding_dependency"] is None


def test_current_revision_change_during_semantic_scoring_blocks_stale_validation_run(
    session: Session,
) -> None:
    original_prompt = "Calculate two plus two."
    draft = generation_draft(session, candidate_json=valid_m1_candidate(original_prompt))
    evaluated_revision = current_review_revision(session, draft)
    add_published_question(session, draft=draft, prompt="Name the capital of France.")

    class RevisionMutatingGrader(PassingGrader):
        def semantic_similarity(
            self, query: str, comparisons: list[str]
        ) -> SemanticSimilarityResult:
            create_edited_revision(session, draft=draft, prompt="What is 9 + 9?")
            return semantic_result([0.1])

    run = verify_current_revision(session, draft=draft, grader_client=RevisionMutatingGrader())

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    expected = fingerprint_prompt(original_prompt)
    assert run.status is ValidationRunStatus.BLOCKED
    assert run.draft_revision_id == evaluated_revision.id
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert run.feature_summary_json["candidate_prompt_fingerprint"] == {
        "version": expected.version,
        "exact_hash": expected.exact_hash,
        "normalized_hash": expected.normalized_hash,
    }
    assert "What is 9 + 9?" not in str(run.feature_summary_json)


def test_unflushed_current_revision_change_blocks_stale_validation_run() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine, autoflush=False) as session:
        original_prompt = "Calculate two plus two."
        draft = generation_draft(session, candidate_json=valid_m1_candidate(original_prompt))
        evaluated_revision = current_review_revision(session, draft)
        add_published_question(session, draft=draft, prompt="Name the capital of France.")
        replacement = GeneratedQuestionDraftRevision(
            id=uuid4(),
            generated_question_draft_id=draft.id,
            revision_number=2,
            candidate_json={**draft.candidate_json, "prompt": "What is 9 + 9?"},
            content_hash="2" * 64,
        )

        class RevisionMutatingGrader(PassingGrader):
            def semantic_similarity(
                self, query: str, comparisons: list[str]
            ) -> SemanticSimilarityResult:
                session.add(replacement)
                draft.current_revision_id = replacement.id
                return semantic_result([0.1])

        run = verify_current_revision(session, draft=draft, grader_client=RevisionMutatingGrader())

        finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
        expected = fingerprint_prompt(original_prompt)
        assert run.status is ValidationRunStatus.BLOCKED
        assert run.draft_revision_id == evaluated_revision.id
        assert finding.evidence_json == {"category": "similarity_unavailable"}
        assert run.feature_summary_json["candidate_prompt_fingerprint"] == {
            "version": expected.version,
            "exact_hash": expected.exact_hash,
            "normalized_hash": expected.normalized_hash,
        }
        assert "What is 9 + 9?" not in str(run.feature_summary_json)


def test_valid_m1_candidate_persists_a_passing_run_and_rerun(session: Session) -> None:
    assert hasattr(verification, "run_candidate_verification")
    draft = generation_draft(session)

    first = verify_current_revision(session, draft=draft, grader_client=PassingGrader())
    second = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert first.status is ValidationRunStatus.PASSED
    assert first.run_number == 1
    assert first.findings == []
    assert second.run_number == 2
    assert draft.validation_runs == [first, second]


def test_m1_verification_runs_expected_empty_boundary_and_outside_probes_in_order(
    session: Session,
) -> None:
    candidate = valid_m1_candidate("Calculate two and one half.")
    candidate["rule_json"] = {"expected": 2.5, "tolerance": 0.25}
    grader = RecordingM1Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, candidate_json=candidate),
        grader_client=grader,
    )

    assert [request[2]["text"] for request in grader.grade_requests] == [
        "2.5",
        "",
        "2.25",
        "2.75",
        "1.25",
        "3.75",
    ]
    assert all(request[0] == "M1" and request[3] == "1" for request in grader.grade_requests)
    assert run.status is ValidationRunStatus.PASSED


def test_m1_zero_tolerance_retains_duplicate_boundary_probes(session: Session) -> None:
    candidate = valid_m1_candidate("Calculate four.")
    candidate["rule_json"] = {"expected": 4, "tolerance": 0}
    grader = RecordingM1Grader()

    verify_current_revision(
        session,
        draft=generation_draft(session, candidate_json=candidate),
        grader_client=grader,
    )

    assert [request[2]["text"] for request in grader.grade_requests] == [
        "4",
        "",
        "4",
        "4",
        "3",
        "5",
    ]


def test_m1_negative_numbers_use_safe_decimal_probe_text(session: Session) -> None:
    candidate = valid_m1_candidate("Calculate a negative number.")
    candidate["rule_json"] = {"expected": -3, "tolerance": 0.5}
    grader = RecordingM1Grader()

    verify_current_revision(
        session,
        draft=generation_draft(session, candidate_json=candidate),
        grader_client=grader,
    )

    assert [request[2]["text"] for request in grader.grade_requests] == [
        "-3",
        "",
        "-3.5",
        "-2.5",
        "-4.5",
        "-1.5",
    ]


def test_m1_large_expected_preserves_exact_outside_tolerance_probes(session: Session) -> None:
    expected = 1e30
    rule_json = {"expected": expected, "tolerance": 0}
    probes = verification._m1_probes(expected, 0)

    assert [probe.text for probe in probes] == [
        "1E+30",
        "",
        "1E+30",
        "1E+30",
        "999999999999999999999999999999",
        "1000000000000000000000000000001",
    ]
    grader = DeterministicE2EGraderClient("")
    decisions = [
        grader.grade(
            "M1", rule_json, {"format": "text-v1", "text": probe.text}, policy_version="1"
        ).decision
        for probe in probes
    ]
    assert decisions == [
        "auto_accepted",
        "auto_rejected",
        "auto_accepted",
        "auto_accepted",
        "auto_rejected",
        "auto_rejected",
    ]

    run = verify_current_revision(
        session,
        draft=generation_draft(
            session,
            candidate_json={
                **valid_m1_candidate("Calculate a large number."),
                "rule_json": rule_json,
            },
        ),
        grader_client=grader,
    )

    assert run.status is ValidationRunStatus.PASSED


def test_m1_tiny_expected_preserves_unit_outside_tolerance_probes() -> None:
    probes = verification._m1_probes(1e-30, 0)

    assert [probe.text for probe in probes] == [
        "1E-30",
        "",
        "1E-30",
        "1E-30",
        f"-0.{'9' * 30}",
        f"1.{'0' * 29}1",
    ]


def test_m1_nonzero_tolerance_preserves_carry_outside_probe(session: Session) -> None:
    rule_json = {"expected": 999, "tolerance": 1}
    probes = verification._m1_probes(999, 1)

    assert [probe.text for probe in probes] == ["999", "", "998", "1E+3", "997", "1001"]
    grader = PassingGrader()
    upper_result = grader.grade(
        "M1", rule_json, {"format": "text-v1", "text": probes[3].text}, policy_version="1"
    )
    above_result = grader.grade(
        "M1", rule_json, {"format": "text-v1", "text": probes[5].text}, policy_version="1"
    )
    assert upper_result.decision == "auto_accepted"
    assert above_result.decision == "auto_rejected"


def test_m1_negative_nonzero_tolerance_preserves_carry_outside_probe() -> None:
    probes = verification._m1_probes(-999, 1)

    assert [probe.text for probe in probes] == ["-999", "", "-1E+3", "-998", "-1001", "-997"]


@pytest.mark.parametrize(
    ("probe_id", "response"),
    [
        *(
            (probe_id, GradeResult("auto_rejected", 0, {"secret": "grader evidence"}, "fake-m1-v1"))
            for probe_id in (
                "expected_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
            )
        ),
        *(
            (probe_id, GradeResult("auto_accepted", 1, {"secret": "grader evidence"}, "fake-m1-v1"))
            for probe_id in (
                "empty_answer",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult(
                    "auto_accepted", float("nan"), {"secret": "grader evidence"}, "fake-m1-v1"
                ),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult("auto_accepted", None, {"secret": "grader evidence"}, "fake-m1-v1"),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult("auto_accepted", "1", {"secret": "grader evidence"}, "fake-m1-v1"),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (probe_id, None)
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (probe_id, object())
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (probe_id, M1ResultWithoutDecision())
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult("auto_accepted", True, {"secret": "grader evidence"}, "fake-m1-v1"),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult("auto_accepted", False, {"secret": "grader evidence"}, "fake-m1-v1"),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (
                probe_id,
                GradeResult(
                    "auto_accepted",
                    ExplosiveM1Score(1),
                    {"secret": "grader evidence"},
                    "fake-m1-v1",
                ),
            )
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
        *(
            (probe_id, RuntimeError("grader exception secret"))
            for probe_id in (
                "expected_answer",
                "empty_answer",
                "lower_tolerance_boundary",
                "upper_tolerance_boundary",
                "below_tolerance_boundary",
                "above_tolerance_boundary",
            )
        ),
    ],
)
def test_m1_invalid_probe_results_are_safely_blocked(
    session: Session, probe_id: str, response: object
) -> None:
    probe_texts = {
        "expected_answer": "2.5",
        "empty_answer": "",
        "lower_tolerance_boundary": "2.25",
        "upper_tolerance_boundary": "2.75",
        "below_tolerance_boundary": "1.25",
        "above_tolerance_boundary": "3.75",
    }
    candidate = valid_m1_candidate("Calculate two and one half.")
    candidate["rule_json"] = {"expected": 2.5, "tolerance": 0.25}
    grader = RecordingM1Grader({probe_texts[probe_id]: response})

    run = verify_current_revision(
        session,
        draft=generation_draft(session, candidate_json=candidate),
        grader_client=grader,
    )

    finding = next(item for item in run.findings if item.code == "m1_grader_probe_failed")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": probe_id}
    assert [request[2]["text"] for request in grader.grade_requests] == [
        "2.5",
        "",
        "2.25",
        "2.75",
        "1.25",
        "3.75",
    ]
    persisted_values = (finding.evidence_json, finding.remediation)
    assert all(
        secret not in str(value)
        for secret in (
            "2.5",
            "0.25",
            "grader evidence",
            "grader exception secret",
            "numeric comparison secret",
        )
        for value in persisted_values
    )


@pytest.mark.parametrize(
    ("policy_version", "rule_json"),
    [
        ("1", {"expected": "four", "tolerance": 0}),
        ("2", {"expected": 4, "tolerance": 0}),
        (None, {"expected": 4, "tolerance": 0}),
        (1, {"expected": 4, "tolerance": 0}),
    ],
)
def test_m1_invalid_schema_or_policy_version_skips_type_specific_grader_calls(
    session: Session, policy_version: object, rule_json: dict[str, object]
) -> None:
    candidate = valid_m1_candidate("Calculate four.")
    candidate["policy_version"] = policy_version
    candidate["rule_json"] = rule_json
    grader = RecordingM1Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, candidate_json=candidate),
        grader_client=grader,
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_valid_m2_candidate_normalizes_and_probes(session: Session) -> None:
    draft = generation_draft(
        session,
        allowed_question_types=["M2"],
        candidate_json=valid_m2_candidate(),
    )
    grader = PassingM2Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert grader.normalization_requests == [{"mathjson": ["Add", "x", 1], "variables": ["x"]}]
    expected = ["Add", "x", 1]
    assert [request[0] for request in grader.grade_requests] == ["M2"] * 5
    assert [request[2]["mathjson"] for request in grader.grade_requests] == [
        expected,
        ["Add", expected, 1],
        None,
        ["Divide", 1, 0],
        _nested_negate_probe(depth=21),
    ]
    assert [request[3] for request in grader.grade_requests] == ["2"] * 5


def test_m2_offset_review_is_valid_at_the_grader_depth_boundary(session: Session) -> None:
    draft = generation_draft(
        session,
        allowed_question_types=["M2"],
        candidate_json=valid_m2_candidate(),
    )
    grader = PassingM2Grader(offset_decision="needs_review")

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert len(grader.grade_requests) == 5


@pytest.mark.parametrize(
    ("probe_index", "probe_id"),
    [
        (0, "expected_mathjson"),
        (1, "one_unit_offset"),
        (2, "empty_mathjson"),
        (3, "zero_denominator"),
        (4, "resource_limit"),
    ],
)
@pytest.mark.parametrize(
    "failure_kind",
    ["unexpected_decision", "non_finite_score", "wrong_nonzero_score", "exception"],
)
def test_m2_probe_failures_are_sanitized_and_do_not_short_circuit(
    session: Session,
    probe_index: int,
    probe_id: str,
    failure_kind: str,
) -> None:
    candidate = valid_m2_candidate()
    assert candidate["rule_json"]["required_form"] == "expanded"
    draft = generation_draft(
        session,
        allowed_question_types=["M2"],
        candidate_json=candidate,
    )
    grader = PassingM2Grader(
        failing_probe_index=probe_index,
        failure_kind=failure_kind,
    )

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    failures = [item for item in run.findings if item.code == "m2_grader_probe_failed"]
    assert run.status is ValidationRunStatus.BLOCKED
    assert len(grader.normalization_requests) == 1
    assert len(grader.grade_requests) == 5
    assert len(failures) == 1
    assert failures[0].evidence_json == {"probe": probe_id}
    persisted_failure = f"{failures[0].evidence_json!r} {failures[0].remediation}"
    assert "['Add', 'x', 1]" not in persisted_failure
    assert "['Divide', 1, 0]" not in persisted_failure
    assert "Negate" not in persisted_failure
    assert "grader diagnostic" not in persisted_failure
    assert "raw MathJSON" not in persisted_failure


def test_valid_e2_candidate_probes_every_accepted_form(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E2"], candidate_json=valid_e2_candidate()
    )
    grader = PassingE2Grader()
    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert grader.grade_requests == [
        ("E2", draft.candidate_json["rule_json"], {"format": "text-v1", "text": "went"}, "1")
    ]


def test_e2_normalized_duplicate_forms_are_blocked(session: Session) -> None:
    duplicate = valid_e2_candidate()
    duplicate["rule_json"] = {"lemma": "go", "accepted_forms": ["Went", " went."]}
    duplicate_draft = generation_draft(
        session, allowed_question_types=["E2"], candidate_json=duplicate
    )

    duplicate_run = verify_current_revision(
        session, draft=duplicate_draft, grader_client=PassingE2Grader()
    )

    finding = next(item for item in duplicate_run.findings if item.code == "e2_forms_invalid")
    assert finding.evidence_json == {"reason": "normalized_duplicate", "accepted_form_count": 2}


@pytest.mark.parametrize("grader", [FailingE2Grader(), PartialE2Grader()])
def test_e2_grader_failure_is_safely_blocked(session: Session, grader: PassingE2Grader) -> None:
    failed_draft = generation_draft(
        session, allowed_question_types=["E2"], candidate_json=valid_e2_candidate()
    )
    failed_run = verify_current_revision(session, draft=failed_draft, grader_client=grader)

    finding = next(item for item in failed_run.findings if item.code == "e2_grader_probe_failed")
    assert finding.evidence_json == {"probe": "accepted_forms", "accepted_form_count": 1}
    assert "went" not in finding.remediation


def test_e2_schema_invalid_rules_do_not_call_the_grader(session: Session) -> None:
    candidate = valid_e2_candidate()
    candidate["rule_json"] = {"lemma": "go", "accepted_forms": []}
    draft = generation_draft(session, allowed_question_types=["E2"], candidate_json=candidate)
    grader = PassingE2Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_valid_e3_candidate_probes_prompt_and_reference_answers(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E3"], candidate_json=valid_e3_candidate()
    )
    grader = PassingE3Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert [request[2]["text"] for request in grader.grade_requests] == [
        draft.candidate_json["prompt"],
        "I went to the park.",
        "We travelled by train.",
    ]
    assert all(request[1]["grammar_feedback_required"] is True for request in grader.grade_requests)
    assert draft.candidate_json["rule_json"]["grammar_feedback_required"] is False


def test_e3_grammar_matches_are_sanitized_warnings(session: Session) -> None:
    candidate = valid_e3_candidate()
    candidate["rule_json"] = {
        "grammar_feedback_required": False,
        "accepted_answers": ["I went to the park."],
    }
    draft = generation_draft(session, allowed_question_types=["E3"], candidate_json=candidate)

    run = verify_current_revision(
        session,
        draft=draft,
        grader_client=PassingE3Grader(feedback=[{"type": "grammar"}, {"type": "grammar"}]),
    )

    warnings = [finding for finding in run.findings if finding.code == "e3_grammar_warning"]
    assert run.status is ValidationRunStatus.WARNING
    assert [finding.evidence_json for finding in warnings] == [
        {"target": "prompt", "grammar_match_count": 2, "reference_answer_count": 1},
        {"target": "reference_answers", "grammar_match_count": 2, "reference_answer_count": 1},
    ]


@pytest.mark.parametrize(
    "grader",
    [
        FailingE3Grader(),
        UnexpectedE3DecisionGrader(),
        MalformedE3FeedbackGrader(),
        DependencyE3Grader(),
    ],
)
def test_e3_grammar_probe_failures_are_safely_blocked(
    session: Session, grader: PassingE3Grader
) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E3"], candidate_json=valid_e3_candidate()
    )

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e3_grammar_probe_failed")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"target": "prompt", "reference_answer_count": 2}
    assert "LanguageTool diagnostic" not in finding.remediation
    assert "Write one sentence about a trip." not in finding.remediation


def test_e3_schema_invalid_rules_do_not_call_the_grader(session: Session) -> None:
    candidate = valid_e3_candidate()
    candidate["rule_json"] = {"max_score": 1}
    draft = generation_draft(session, allowed_question_types=["E3"], candidate_json=candidate)
    grader = PassingE3Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_valid_e4_candidate_probes_every_evidence_phrase(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E4"], candidate_json=valid_e4_candidate()
    )
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert [request[2]["text"] for request in grader.grade_requests] == [
        "because the bridge was closed",
        "they arrived late",
    ]
    assert [request[1]["max_score"] for request in grader.grade_requests] == [2.0, 1.0]
    assert all(len(request[1]["scoring_points"]) == 1 for request in grader.grade_requests)
    assert draft.candidate_json["rule_json"]["scoring_points"][0]["score"] == 2


@pytest.mark.parametrize(
    ("material", "reason"),
    [
        (None, "missing_or_blank"),
        ({}, "missing_or_blank"),
        (" " * 2, "missing_or_blank"),
        ("x" * 8_001, "too_long"),
    ],
)
def test_e4_missing_or_oversized_material_blocks_without_grader_calls(
    session: Session, material: object, reason: str
) -> None:
    candidate = valid_e4_candidate()
    if material is None:
        candidate.pop("reading_material")
    else:
        candidate["reading_material"] = material
    grader = PassingE4Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=grader,
    )

    finding = next(item for item in run.findings if item.code == "e4_reading_material_invalid")
    assert finding.evidence_json == {
        "reason": reason,
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


def test_legacy_persisted_e4_candidate_without_material_blocks_without_grader_calls(
    session: Session,
) -> None:
    candidate = valid_e4_candidate()
    candidate.pop("reading_material")
    grader = PassingE4Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=grader,
    )

    finding = next(item for item in run.findings if item.code == "e4_reading_material_invalid")
    assert finding.evidence_json == {
        "reason": "missing_or_blank",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


def test_e4_material_mismatch_blocks_before_grader_and_never_echoes_text(
    session: Session,
) -> None:
    candidate = valid_e4_candidate()
    candidate["reading_material"] = "The road was open, and the students arrived early."
    grader = PassingE4Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=grader,
    )

    finding = next(item for item in run.findings if item.code == "e4_evidence_material_mismatch")
    assert finding.evidence_json == {
        "probe": "reading_material",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []
    assert "road was open" not in finding.remediation


def test_e4_punctuation_only_evidence_is_invalid_without_grader_calls(
    session: Session,
) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["scoring_points"] = [
        {
            "id": "reason",
            "evidence_phrases": ["."],
            "score": 2,
        }
    ]
    candidate["rule_json"]["max_score"] = 2
    grader = PassingE4Grader()

    run = verify_current_revision(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=grader,
    )

    finding = next(item for item in run.findings if item.code == "e4_scoring_points_invalid")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "reason": "normalized_empty_phrase",
        "scoring_point_count": 1,
        "evidence_phrase_count": 1,
    }
    assert grader.grade_requests == []


def test_e4_normalized_material_match_and_material_safety_scan(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["reading_material"] = "BECAUSE the bridge was closed.  THEY arrived late!"
    assert (
        verify_current_revision(
            session,
            draft=generation_draft(
                session, allowed_question_types=["E4"], candidate_json=candidate
            ),
            grader_client=PassingE4Grader(),
        ).status
        is ValidationRunStatus.PASSED
    )

    candidate["reading_material"] = "self-harm instructions"
    unsafe = verify_current_revision(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=PassingE4Grader(),
    )
    assert next(
        item for item in unsafe.findings if item.code == "unsafe_minor_content"
    ).evidence_json == {
        "category": "self_harm_instruction",
        "rule_id": "self-harm-instruction-v1",
        "policy_version": "minor-content-policy-v1",
    }


def test_e4_normalized_duplicate_point_ids_are_blocked(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["scoring_points"][1]["id"] = " Reason "
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_scoring_points_invalid")
    assert finding.evidence_json == {
        "reason": "normalized_duplicate_id",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


def test_e4_normalized_duplicate_phrases_are_blocked(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["scoring_points"][1]["evidence_phrases"] = [
        " Because the bridge was closed."
    ]
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_scoring_points_invalid")
    assert finding.evidence_json == {
        "reason": "normalized_duplicate_phrase",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


def test_e4_overlapping_phrases_across_points_are_blocked(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["scoring_points"][0]["evidence_phrases"] = ["bridge closed"]
    candidate["rule_json"]["scoring_points"][1]["evidence_phrases"] = ["closed"]
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_scoring_points_invalid")
    assert finding.evidence_json == {
        "reason": "overlapping_phrase",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


def test_e4_score_total_mismatch_is_blocked(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["max_score"] = 4
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_score_total_invalid")
    assert finding.evidence_json == {
        "scoring_point_count": 2,
        "point_score_total": 3.0,
        "max_score": 4.0,
    }
    assert grader.grade_requests == []


def test_e4_score_total_uses_floating_point_tolerance(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["max_score"] = 0.9
    candidate["rule_json"]["scoring_points"][0]["score"] = 0.7
    candidate["rule_json"]["scoring_points"][1]["score"] = 0.2
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingE4Grader())

    assert run.status is ValidationRunStatus.PASSED


@pytest.mark.parametrize("target", ["point_score", "max_score"])
def test_e4_non_finite_scores_are_blocked_without_grader_calls(
    session: Session, target: str
) -> None:
    candidate = valid_e4_candidate()
    if target == "point_score":
        candidate["rule_json"]["scoring_points"][0]["score"] = float("nan")
    else:
        candidate["rule_json"]["max_score"] = float("nan")
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_score_total_invalid")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "reason": "non_finite_score",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert grader.grade_requests == []


@pytest.mark.parametrize(
    "grader",
    [FailingE4Grader(), UnexpectedE4DecisionGrader(), PartialE4Grader(), NonFiniteE4Grader()],
)
def test_e4_invalid_grader_probes_are_safely_blocked(
    session: Session, grader: PassingE4Grader
) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E4"], candidate_json=valid_e4_candidate()
    )

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "e4_grader_probe_failed")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "probe": "evidence_phrases",
        "scoring_point_count": 2,
        "evidence_phrase_count": 2,
    }
    assert "similarity dependency diagnostic" not in finding.remediation
    assert "because the bridge was closed" not in finding.remediation


def test_e4_schema_invalid_rules_do_not_call_the_grader(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"] = {"max_score": 1}
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_m2_normalizer_failure_is_safely_blocked(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )

    run = verify_current_revision(session, draft=draft, grader_client=FailingM2Normalizer())

    finding = next(item for item in run.findings if item.code == "m2_mathjson_invalid")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": "expected_mathjson"}
    assert "unsafe expression" not in finding.remediation


@pytest.mark.parametrize("grader", [FailingM2Grader(), PartialM2Grader()])
def test_m2_failed_probe_is_safely_blocked(session: Session, grader: PassingM2Grader) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "m2_grader_probe_failed")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": "expected_mathjson"}


def test_m2_full_score_tolerates_grader_float_representation(session: Session) -> None:
    candidate = valid_m2_candidate()
    candidate["rule_json"] = {
        "expected": ["Add", "x", 1],
        "variables": ["x"],
        "required_form": "expanded",
        "form_score": 0.2,
        "max_score": 0.9,
    }
    draft = generation_draft(session, allowed_question_types=["M2"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=FloatingPointM2Grader())

    assert run.status is ValidationRunStatus.PASSED


@pytest.mark.parametrize(
    ("prompt", "expected_observed"),
    [
        ("One two three four.", None),
        ("One two three four five.", 5),
    ],
)
def test_grade_complexity_warns_only_above_prompt_unit_limit(
    session: Session, prompt: str, expected_observed: int | None
) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate(prompt))
    configure_grade_complexity_rules(session, draft, {"max_prompt_units": 4})

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    findings = [item for item in run.findings if item.code == "grade_complexity_warning"]
    if expected_observed is None:
        assert findings == []
    else:
        assert findings[0].evidence_json == {
            "grade_level": "G5",
            "metric": "max_prompt_units",
            "observed": expected_observed,
            "limit": 4,
        }


def test_grade_complexity_uses_cjk_units_and_largest_sentence(session: Session) -> None:
    assert verification._lexical_unit_count("One 2's 中文") == 4
    assert verification._lexical_unit_count("élève") == 1
    assert verification._lexical_unit_count("e\u0301lève") == 1
    assert verification._lexical_unit_count("A\u030angstrom") == 1
    assert verification._max_sentence_units("One two. Three four five.") == 3

    draft = generation_draft(
        session, candidate_json=valid_m1_candidate("One two. Three four five.")
    )
    configure_grade_complexity_rules(session, draft, {"max_sentence_units": 2})

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = next(item for item in run.findings if item.code == "grade_complexity_warning")
    assert finding.evidence_json == {
        "grade_level": "G5",
        "metric": "max_sentence_units",
        "observed": 3,
        "limit": 2,
    }


def test_grade_complexity_measures_m1_numeric_values_without_echoing_rule_fields(
    session: Session,
) -> None:
    candidate = {
        "question_type": "M1",
        "policy_version": "1",
        "prompt": "Add the numbers.",
        "rule_json": {"expected": 11, "tolerance": 10},
        "explanation": "Use addition.",
    }
    draft = generation_draft(session, allowed_question_types=["M1"], candidate_json=candidate)
    configure_grade_complexity_rules(session, draft, {"max_numeric_absolute_value": 10})

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = next(item for item in run.findings if item.code == "grade_complexity_warning")
    assert finding.evidence_json == {
        "grade_level": "G5",
        "metric": "max_numeric_absolute_value",
        "observed": 11,
        "limit": 10,
    }
    assert "expected" not in finding.evidence_json
    assert "tolerance" not in finding.evidence_json
    assert "expected" not in finding.remediation
    assert "tolerance" not in finding.remediation


def test_grade_complexity_compares_m2_numeric_values_as_decimals_before_serializing() -> None:
    findings = verification._grade_complexity_findings(
        rules={"max_numeric_absolute_value": 10},
        grade_level="G5",
        prompt="Find the value.",
        question_type="M2",
        rule_json={},
        normalized_m2_ast={"type": "number", "value": "10.0000000000000001"},
    )

    assert [finding.code for finding in findings] == ["grade_complexity_warning"]
    assert findings[0].evidence == {
        "grade_level": "G5",
        "metric": "max_numeric_absolute_value",
        "observed": 10.000000000000002,
        "limit": 10,
    }
    assert findings[0].evidence["observed"] > findings[0].evidence["limit"]


def test_grade_complexity_reuses_m2_normalization_for_safe_metrics(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=complex_m2_candidate()
    )
    configure_grade_complexity_rules(
        session,
        draft,
        {"max_math_operation_nodes": 1},
    )
    grader = ComplexM2Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    findings = [item for item in run.findings if item.code == "grade_complexity_warning"]
    assert [item.evidence_json["metric"] for item in findings] == ["max_math_operation_nodes"]
    assert findings[0].evidence_json == {
        "grade_level": "G5",
        "metric": "max_math_operation_nodes",
        "observed": 2,
        "limit": 1,
    }
    assert grader.normalization_requests == [
        {
            "mathjson": ["Add", "x", ["Multiply", 2, "x"]],
            "variables": ["x"],
        }
    ]
    for finding in findings:
        assert "MathJSON" not in finding.remediation
        assert "ast" not in finding.evidence_json
        assert "args" not in finding.evidence_json
        assert "value" not in finding.evidence_json
    assert run.validator_version == "verification-v5"
    assert run.ruleset_version == "rules-v5"


def test_grade_complexity_uses_stable_metric_order_and_skips_absent_rules(session: Session) -> None:
    absent_rules_draft = generation_draft(
        session, candidate_json=valid_m1_candidate("One two three four five.")
    )
    configure_grade_complexity_rules(session, absent_rules_draft, {})
    absent_rules_run = verify_current_revision(
        session, draft=absent_rules_draft, grader_client=PassingGrader()
    )
    assert "grade_complexity_warning" not in finding_codes(absent_rules_run)

    draft = generation_draft(
        session,
        ordinal=2,
        allowed_question_types=["M2"],
        candidate_json={
            **complex_m2_candidate(),
            "prompt": "One two. Three four five.",
        },
    )
    configure_grade_complexity_rules(
        session,
        draft,
        {
            "max_math_operation_nodes": 1,
            "max_prompt_units": 4,
            "max_numeric_absolute_value": 10,
            "max_sentence_units": 2,
        },
    )

    run = verify_current_revision(session, draft=draft, grader_client=ComplexM2Grader())

    findings = [item for item in run.findings if item.code == "grade_complexity_warning"]
    assert [item.evidence_json["metric"] for item in findings] == [
        "max_prompt_units",
        "max_sentence_units",
        "max_math_operation_nodes",
    ]
    for finding in findings:
        assert set(finding.evidence_json) == {"grade_level", "metric", "observed", "limit"}
        assert "One two" not in finding.remediation
        assert "Add" not in finding.remediation


def test_malformed_persisted_grade_complexity_rules_fail_closed(session: Session) -> None:
    draft = generation_draft(session)
    configure_grade_complexity_rules(session, draft, {"max_prompt_units": True})

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert finding_codes(run) == {"grade_complexity_rules_invalid"}
    finding = run.findings[0]
    assert finding.evidence_json == {"grade_level": "G5"}


def test_m2_unexpected_safe_ast_is_blocked_before_grader_probe(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )
    grader = InvalidSafeAstM2Grader()

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    finding = next(item for item in run.findings if item.code == "m2_mathjson_invalid")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": "expected_mathjson"}
    assert grader.grade_requests == []


def test_m2_rational_safe_ast_supports_numeric_complexity(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )
    configure_grade_complexity_rules(session, draft, {"max_numeric_absolute_value": 1})
    grader = SafeAstM2Grader({"type": "number", "value": "3/2"})

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert "m2_mathjson_invalid" not in finding_codes(run)
    finding = next(item for item in run.findings if item.code == "grade_complexity_warning")
    assert finding.evidence_json == {
        "grade_level": "G5",
        "metric": "max_numeric_absolute_value",
        "observed": 1.5,
        "limit": 1,
    }
    assert grader.normalization_requests == [{"mathjson": ["Add", "x", 1], "variables": ["x"]}]


@pytest.mark.parametrize(
    "ast",
    [
        {"type": "symbol"},
        {"type": "number", "value": "1", "arg": {"type": "symbol", "name": "x"}},
        {"type": "symbol", "name": "x", "unexpected": "field"},
    ],
)
def test_m2_incomplete_or_unknown_safe_ast_is_blocked_before_grader_probe(
    session: Session, ast: dict[str, object]
) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )
    grader = SafeAstM2Grader(ast)

    run = verify_current_revision(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.BLOCKED
    assert finding_codes(run) == {"m2_mathjson_invalid"}
    assert grader.grade_requests == []
    assert len(grader.normalization_requests) == 1


def test_m2_safe_ast_contract_matches_grader_normalizer() -> None:
    ast = normalize_mathjson(["Add", "x", 1], ["x"])

    assert ast == {
        "type": "add",
        "args": [
            {"type": "symbol", "name": "x"},
            {"type": "number", "value": "1"},
        ],
    }
    assert verification._m2_complexity_metrics(ast) == (Decimal("1"), 1)


def test_rule_based_difficulty_signal_uses_safe_m1_numeric_and_text_metrics() -> None:
    lower_numeric = verification._rule_based_difficulty_signal(
        target_difficulty=0.4,
        curriculum_range=(0, 1),
        prompt="One two three four five.",
        question_type="M1",
        rule_json={"expected": 9, "tolerance": 0},
        normalized_m2_ast=None,
    )
    higher_numeric = verification._rule_based_difficulty_signal(
        target_difficulty=0.4,
        curriculum_range=(0, 1),
        prompt="One two three four five.",
        question_type="M1",
        rule_json={"expected": 999, "tolerance": 0},
        normalized_m2_ast=None,
    )

    assert higher_numeric == {
        "version": "rule-based-difficulty-v1",
        "availability": "available",
        "reason": None,
        "target": 0.4,
        "estimated": 0.329,
        "deviation": 0.071,
        "curriculum_range": {"min": 0.0, "max": 1.0},
        "features": [
            {"type": "question_type_baseline", "value": 0.2, "contribution": 0.2},
            {"type": "prompt_units", "value": 5, "contribution": 0.009},
            {"type": "sentence_units", "value": 5, "contribution": 0.02},
            {"type": "numeric_magnitude", "value": 0.5, "contribution": 0.1},
        ],
    }
    assert higher_numeric["estimated"] > lower_numeric["estimated"]


def test_rule_based_difficulty_signal_uses_only_verified_m2_ast_metrics() -> None:
    simple = verification._rule_based_difficulty_signal(
        target_difficulty=0.5,
        curriculum_range=(0, 1),
        prompt="Simplify the expression.",
        question_type="M2",
        rule_json={"expected": ["Add", "secret", 999999]},
        normalized_m2_ast={"type": "number", "value": "1"},
    )
    more_complex = verification._rule_based_difficulty_signal(
        target_difficulty=0.5,
        curriculum_range=(0, 1),
        prompt="Simplify the expression.",
        question_type="M2",
        rule_json={"expected": ["Add", "secret", 999999]},
        normalized_m2_ast={
            "type": "add",
            "args": [
                {"type": "number", "value": "1000"},
                {
                    "type": "mul",
                    "args": [
                        {"type": "number", "value": "10"},
                        {"type": "symbol", "name": "x"},
                    ],
                },
            ],
        },
    )

    assert more_complex["estimated"] > simple["estimated"]
    assert simple["availability"] == "available"
    assert more_complex["availability"] == "available"
    assert {feature["type"] for feature in more_complex["features"]} >= {
        "numeric_magnitude",
        "m2_operation_nodes",
    }
    assert all(
        set(feature) == {"type", "value", "contribution"}
        and isinstance(feature["type"], str)
        and all(isinstance(feature[key], int | float) for key in ("value", "contribution"))
        for feature in more_complex["features"]
    )


def test_rule_based_difficulty_signal_is_stable_and_does_not_echo_candidate_body() -> None:
    prompt = "Do not persist this private prompt value."
    rule_json = {"expected": 12345, "teacher_note": "private rule value"}

    first = verification._rule_based_difficulty_signal(
        target_difficulty=0.2,
        curriculum_range=(0, 0.7),
        prompt=prompt,
        question_type="M1",
        rule_json=rule_json,
        normalized_m2_ast=None,
    )
    second = verification._rule_based_difficulty_signal(
        target_difficulty=0.2,
        curriculum_range=(0, 0.7),
        prompt=prompt,
        question_type="M1",
        rule_json=rule_json,
        normalized_m2_ast=None,
    )

    assert first == second
    assert first["availability"] == "available"
    assert prompt not in str(first)
    assert "private rule value" not in str(first)
    assert 0 <= first["estimated"] <= 1


def test_rule_based_difficulty_signal_omits_m2_math_metrics_without_a_safe_ast() -> None:
    signal = verification._rule_based_difficulty_signal(
        target_difficulty=float("nan"),
        curriculum_range=(0, 1),
        prompt="Simplify.",
        question_type="M2",
        rule_json={"expected": ["Add", "unsafe", 99]},
        normalized_m2_ast=None,
    )

    assert signal["target"] is None
    assert signal["deviation"] is None
    assert signal["availability"] == "available"
    assert {feature["type"] for feature in signal["features"]}.isdisjoint(
        {"numeric_magnitude", "m2_operation_nodes"}
    )


@pytest.mark.parametrize(
    ("target_difficulty", "expected_target"),
    [
        (2, None),
        (1e308, None),
        (10**1000, None),
        (Decimal("0.4"), 0.4),
        (float("nan"), None),
    ],
)
def test_rule_based_difficulty_signal_accepts_only_bounded_finite_targets(
    target_difficulty: object, expected_target: float | None
) -> None:
    signal = verification._rule_based_difficulty_signal(
        target_difficulty=target_difficulty,
        curriculum_range=(0, 1),
        prompt="Find the answer.",
        question_type="M1",
        rule_json={"expected": 4, "tolerance": 0},
        normalized_m2_ast=None,
    )

    assert signal["target"] == expected_target
    if expected_target is None:
        assert signal["deviation"] is None
    else:
        assert isinstance(signal["deviation"], float)
        assert -1 <= signal["deviation"] <= 1


def test_rule_based_difficulty_signal_does_not_read_raw_m2_rules() -> None:
    safe_ast = {
        "type": "add",
        "args": [
            {"type": "number", "value": "1000"},
            {"type": "symbol", "name": "x"},
        ],
    }
    common = {
        "target_difficulty": 0.5,
        "curriculum_range": (0, 1),
        "prompt": "Simplify the expression.",
        "question_type": "M2",
        "normalized_m2_ast": safe_ast,
    }

    first = verification._rule_based_difficulty_signal(
        **common,
        rule_json={"expected": ["Add", "private", 1]},
    )
    second = verification._rule_based_difficulty_signal(
        **common,
        rule_json={
            "expected": ["Add", "private", 10**1000],
            "teacher_note": "do not persist this private rule",
        },
    )

    assert first == second
    assert "private" not in str(first)
    assert "do not persist" not in str(first)


def test_grade_complexity_observations_preserve_m1_and_m2_warning_evidence() -> None:
    m1_findings = verification._grade_complexity_findings(
        rules={"max_prompt_units": 3, "max_numeric_absolute_value": 10},
        grade_level="G5",
        prompt="One two three four.",
        question_type="M1",
        rule_json={"expected": 11, "tolerance": 0},
        normalized_m2_ast=None,
    )
    m2_findings = verification._grade_complexity_findings(
        rules={"max_numeric_absolute_value": 10, "max_math_operation_nodes": 1},
        grade_level="G5",
        prompt="Simplify.",
        question_type="M2",
        rule_json={"expected": ["Add", "private", 10**1000]},
        normalized_m2_ast={
            "type": "add",
            "args": [
                {"type": "number", "value": "11"},
                {
                    "type": "mul",
                    "args": [
                        {"type": "number", "value": "2"},
                        {"type": "symbol", "name": "x"},
                    ],
                },
            ],
        },
    )

    assert [(item.code, item.evidence) for item in m1_findings] == [
        (
            "grade_complexity_warning",
            {
                "grade_level": "G5",
                "metric": "max_prompt_units",
                "observed": 4,
                "limit": 3,
            },
        ),
        (
            "grade_complexity_warning",
            {
                "grade_level": "G5",
                "metric": "max_numeric_absolute_value",
                "observed": 11,
                "limit": 10,
            },
        ),
    ]
    assert [(item.code, item.evidence) for item in m2_findings] == [
        (
            "grade_complexity_warning",
            {
                "grade_level": "G5",
                "metric": "max_numeric_absolute_value",
                "observed": 11,
                "limit": 10,
            },
        ),
        (
            "grade_complexity_warning",
            {
                "grade_level": "G5",
                "metric": "max_math_operation_nodes",
                "observed": 2,
                "limit": 1,
            },
        ),
    ]


def test_invalid_m2_schema_preserves_policy_finding(session: Session) -> None:
    candidate = valid_m2_candidate()
    candidate["rule_json"] = {"variables": ["x"], "max_score": 4}
    draft = generation_draft(session, allowed_question_types=["M2"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingM2Grader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert finding_codes(run) == {"policy_schema_invalid"}


def test_inactive_revision_blocks_the_candidate(session: Session) -> None:
    draft = generation_draft(session, revision_status=CurriculumRevisionStatus.DRAFT)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert "curriculum_revision_inactive" in finding_codes(run)


def test_candidate_for_a_different_objective_revision_is_blocked(session: Session) -> None:
    candidate = valid_m1_candidate("What is 2 + 2?")
    candidate["objective_revision_id"] = str(uuid4())
    draft = generation_draft(session, candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert "curriculum_objective_mismatch" in finding_codes(run)


def test_candidate_difficulty_outside_objective_range_is_blocked(session: Session) -> None:
    candidate = valid_m1_candidate("What is 2 + 2?")
    candidate["difficulty"] = 0.9
    draft = generation_draft(session, candidate_json=candidate)
    draft.job.curriculum_objective_revision.difficulty_max = 0.2

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert "difficulty_out_of_range" in finding_codes(run)


def test_validation_run_persists_safe_rule_based_difficulty_signal(session: Session) -> None:
    prompt = "Teacher-only prompt sentinel: calculate 45 plus 55."
    rule_note = "Teacher-only rule sentinel"
    candidate = valid_m1_candidate(prompt)
    candidate["rule_json"] = {"expected": 100, "tolerance": 0, "teacher_note": rule_note}
    candidate["difficulty"] = 0.6
    draft = generation_draft(session, candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.feature_summary_json["difficulty_signal"] == {
        "version": "rule-based-difficulty-v1",
        "availability": "available",
        "reason": None,
        "target": 0.6,
        "estimated": 0.346,
        "deviation": 0.254,
        "curriculum_range": {"min": 0.0, "max": 1.0},
        "features": [
            {"type": "question_type_baseline", "value": 0.2, "contribution": 0.2},
            {"type": "prompt_units", "value": 8, "contribution": 0.014},
            {"type": "sentence_units", "value": 8, "contribution": 0.032},
            {"type": "numeric_magnitude", "value": 0.5, "contribution": 0.1},
        ],
    }
    assert run.feature_summary_json["finding_count"] == len(run.findings)
    assert run.feature_summary_json["content_policy_version"] == "minor-content-policy-v1"
    assert prompt not in str(run.feature_summary_json)
    assert rule_note not in str(run.feature_summary_json)


def test_invalid_difficulty_persists_null_target_without_changing_blocked_result(
    session: Session,
) -> None:
    candidate = valid_m1_candidate("What is 2 + 2?")
    candidate["difficulty"] = "not-a-number"
    draft = generation_draft(session, candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert "difficulty_out_of_range" in finding_codes(run)
    assert run.feature_summary_json["difficulty_signal"]["target"] is None
    assert run.feature_summary_json["difficulty_signal"]["deviation"] is None
    assert run.feature_summary_json["difficulty_signal"]["availability"] == "available"


def test_validator_exception_persists_safe_fallback_difficulty_signal(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompt = "Teacher-only fallback prompt sentinel"
    draft = generation_draft(session, candidate_json=valid_m1_candidate(prompt))

    def raise_internal_error(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("internal secret diagnostic")

    monkeypatch.setattr(verification, "_evaluate_candidate", raise_internal_error)
    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.feature_summary_json["difficulty_signal"] == {
        "version": "rule-based-difficulty-v1",
        "availability": "unavailable",
        "target": None,
        "estimated": None,
        "deviation": None,
        "curriculum_range": {"min": None, "max": None},
        "features": [],
        "reason": "validator_unavailable",
    }
    assert prompt not in str(run.feature_summary_json)
    assert "secret" not in str(run.feature_summary_json)


def test_disallowed_type_and_invalid_policy_are_blocked(session: Session) -> None:
    draft = generation_draft(
        session,
        allowed_question_types=["E1"],
        candidate_json={
            "question_type": "M1",
            "policy_version": "1",
            "prompt": "What is 2 + 2?",
            "rule_json": {"expected": "four", "tolerance": 0},
            "explanation": "Add the two whole numbers.",
        },
    )

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert {
        "question_type_not_allowed",
        "policy_schema_invalid",
    } <= finding_codes(run)


def test_m1_grader_failure_is_blocked_without_exception_text(session: Session) -> None:
    draft = generation_draft(session)

    run = verify_current_revision(session, draft=draft, grader_client=FailingGrader())

    finding = next(finding for finding in run.findings if finding.code == "m1_grader_probe_failed")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": "expected_answer"}
    assert "unavailable" not in str(finding.evidence_json)


def test_e1_normalized_duplicate_answers_are_blocked_without_grader(session: Session) -> None:
    draft = generation_draft(
        session,
        candidate_json={
            "question_type": "E1",
            "policy_version": "2",
            "prompt": "Choose the correct word.",
            "rule_json": {
                "accepted_answers": ["Cat", "  cat  "],
                "normalization": {"unicode_form": "NFKC", "ignore_case": True},
            },
            "explanation": "Use the word that names the animal.",
        },
    )

    run = verify_current_revision(session, draft=draft, grader_client=FailingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert finding_codes(run) == {"e1_answers_invalid"}


def test_e1_unsafe_accepted_answer_is_blocked_without_echoing_answer(session: Session) -> None:
    draft = generation_draft(
        session,
        candidate_json={
            "question_type": "E1",
            "policy_version": "2",
            "prompt": "Choose the safe word.",
            "rule_json": {
                "accepted_answers": ["pornographic"],
                "normalization": {"unicode_form": "NFKC", "ignore_case": True},
            },
            "explanation": "Choose a word from the list.",
        },
    )

    run = verify_current_revision(session, draft=draft, grader_client=FailingGrader())

    finding = next(finding for finding in run.findings if finding.code == "unsafe_minor_content")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "category": "adult_content",
        "rule_id": "adult-explicit-v1",
        "policy_version": "minor-content-policy-v1",
    }
    assert "pornographic" not in str(finding.evidence_json)


def test_content_policy_findings_are_sanitized_and_ordered(session: Session) -> None:
    candidate = {
        "question_type": "E1",
        "policy_version": "2",
        "prompt": "Choose the safe word.",
        "reading_material": "explicit adult content",
        "rule_json": {
            "accepted_answers": ["how to cut yourself"],
            "normalization": {"unicode_form": "NFKC", "ignore_case": True},
        },
        "explanation": "Choose a word from the list.",
    }
    draft = generation_draft(session, allowed_question_types=["E1"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    safety_findings = [
        finding for finding in run.findings if finding.code == "unsafe_minor_content"
    ]
    assert run.status is ValidationRunStatus.BLOCKED
    assert [finding.evidence_json for finding in safety_findings] == [
        {
            "category": "adult_content",
            "rule_id": "adult-explicit-v1",
            "policy_version": "minor-content-policy-v1",
        },
        {
            "category": "self_harm_instruction",
            "rule_id": "self-harm-instruction-v1",
            "policy_version": "minor-content-policy-v1",
        },
    ]
    persisted_values = [
        *(finding.evidence_json for finding in safety_findings),
        *(finding.remediation for finding in safety_findings),
        run.feature_summary_json,
    ]
    assert all(
        sensitive_text not in str(value)
        for sensitive_text in ("explicit adult content", "how to cut yourself")
        for value in persisted_values
    )
    assert run.validator_version == "verification-v5"
    assert run.ruleset_version == "rules-v5"
    assert run.feature_summary_json["content_policy_version"] == "minor-content-policy-v1"


def test_content_policy_mature_theme_requires_teacher_review(session: Session) -> None:
    candidate = {
        "question_type": "E1",
        "policy_version": "2",
        "prompt": "Discuss drug use in a historical context.",
        "rule_json": {
            "accepted_answers": ["history"],
            "normalization": {"unicode_form": "NFKC", "ignore_case": True},
        },
        "explanation": "Select the subject being discussed.",
    }
    draft = generation_draft(session, allowed_question_types=["E1"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = next(
        finding for finding in run.findings if finding.code == "mature_theme_requires_review"
    )
    assert run.status is ValidationRunStatus.WARNING
    assert finding.evidence_json == {
        "category": "substance_use",
        "rule_id": "substance-use-v1",
        "policy_version": "minor-content-policy-v1",
    }


def test_content_policy_blocks_direct_reproduction_requests(session: Session) -> None:
    candidate = {
        "question_type": "E1",
        "policy_version": "2",
        "prompt": "Copy textbook page 42 verbatim.",
        "rule_json": {
            "accepted_answers": ["done"],
            "normalization": {"unicode_form": "NFKC", "ignore_case": True},
        },
        "explanation": "Follow the instruction.",
    }
    draft = generation_draft(session, allowed_question_types=["E1"], candidate_json=candidate)

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = next(
        finding for finding in run.findings if finding.code == "copyright_reproduction_risk"
    )
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {
        "category": "direct_reproduction_request",
        "rule_id": "direct-reproduction-request-v1",
        "policy_version": "minor-content-policy-v1",
    }


def test_duplicate_and_unsafe_content_produce_explainable_findings(session: Session) -> None:
    draft = generation_draft(session)
    duplicate = GeneratedQuestionDraft(
        job_id=draft.job_id,
        generation_attempt_id=draft.generation_attempt_id,
        ordinal=2,
        content_hash="d" * 64,
        candidate_json={
            **draft.candidate_json,
            "prompt": "  WHAT   IS 2 + 2?  ",
            "explanation": "This contains pornographic material.",
        },
        teacher_state="pending_review",
    )
    session.add(duplicate)
    session.flush()
    session.add(
        GeneratedQuestionDraftRevision(
            id=duplicate.current_revision_id,
            generated_question_draft_id=duplicate.id,
            revision_number=1,
            candidate_json=duplicate.candidate_json,
            content_hash=duplicate.content_hash,
        )
    )
    session.flush()

    run = verify_current_revision(session, draft=duplicate, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert {"duplicate_normalized_prompt", "unsafe_minor_content"} <= finding_codes(run)
    unsafe_finding = next(
        finding for finding in run.findings if finding.code == "unsafe_minor_content"
    )
    assert unsafe_finding.evidence_json == {
        "category": "adult_content",
        "rule_id": "adult-explicit-v1",
        "policy_version": "minor-content-policy-v1",
    }


def test_missing_prompt_or_explanation_is_blocked(session: Session) -> None:
    draft = generation_draft(
        session,
        candidate_json={
            "question_type": "M1",
            "policy_version": "1",
            "prompt": " ",
            "rule_json": {"expected": 4, "tolerance": 0},
            "explanation": "",
        },
    )

    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    assert run.status is ValidationRunStatus.BLOCKED
    assert "prompt_or_explanation_invalid" in finding_codes(run)


def test_unexpected_validator_error_is_persisted_without_raw_exception(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = generation_draft(session)

    def raise_internal_error(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("internal secret diagnostic")

    monkeypatch.setattr(verification, "_evaluate_candidate", raise_internal_error)
    run = verify_current_revision(session, draft=draft, grader_client=PassingGrader())

    finding = next(finding for finding in run.findings if finding.code == "validator_unavailable")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"category": "internal_validation_error"}
    assert "secret" not in finding.remediation
