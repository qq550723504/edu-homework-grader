import importlib.util
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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
    GeneratedQuestionDraft,
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
    def __init__(self) -> None:
        self.normalization_requests: list[dict[str, object]] = []
        self.grade_requests: list[tuple[str, dict[str, object], dict[str, object], str | None]] = []

    def normalize_math_answer(self, answer_json: dict[str, object]) -> dict[str, object]:
        self.normalization_requests.append(answer_json)
        return {"kind": "expression", "value": "x_plus_1"}

    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
        *,
        policy_version: str | None = None,
    ) -> GradeResult:
        self.grade_requests.append((question_type, rule_json, answer_json, policy_version))
        return GradeResult(
            decision="auto_accepted",
            score=4,
            evidence={"probe": "accepted"},
            grader_version="fake-m2-v1",
        )


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
        return GradeResult(
            decision="auto_accepted",
            score=0.9 - 0.2 + 0.2,
            evidence={},
            grader_version="fake-m2-v1",
        )


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
    return draft


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


def test_exact_batch_duplicate_is_blocked_without_source_text(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(session, draft=draft, prompt="What is 2 + 2?", ordinal=2)
    grader = SemanticGrader([])

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_exact_prompt")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"comparison": "batch_candidate", "method": "exact_hash"}
    assert finding.severity.value == "blocked"
    assert grader.semantic_requests == []


def test_normalized_batch_duplicate_is_blocked_without_source_text(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(session, draft=draft, prompt="  ＷＨＡＴ   IS 2 + 2?  ", ordinal=2)
    grader = SemanticGrader([])

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_near_match")
    assert finding.evidence_json == {
        "comparison": "published_question",
        "method": "semantic",
        "threshold_band": "at_or_above",
    }
    assert "What is 2 + 2?" not in str(finding.evidence_json)
    assert run.feature_summary_json == {
        "finding_count": len(run.findings),
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


def test_semantic_same_batch_candidate_is_blocked(session: Session) -> None:
    draft = generation_draft(session)
    add_batch_draft(
        session,
        draft=draft,
        prompt="Calculate the sum of two and two.",
        ordinal=2,
    )

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=SemanticGrader([[0.92]])
    )

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=MutatingSemanticGrader()
    )

    assert run.status is ValidationRunStatus.PASSED
    assert run.feature_summary_json == {
        "finding_count": 0,
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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert [len(comparisons) for _, comparisons in grader.semantic_requests] == [128, 1]
    assert run.feature_summary_json["comparison_counts"] == {
        "published_question": 0,
        "batch_candidate": 129,
    }


def test_distinct_candidate_passes_duplicate_gate(session: Session) -> None:
    draft = generation_draft(session, candidate_json=valid_m1_candidate("Calculate two plus two."))
    add_published_question(session, draft=draft, prompt="Name the capital of France.")

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=SemanticGrader([[0.14]])
    )

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=MissingSemanticGrader()
    )

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=SemanticGrader([scores])
    )

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"category": "similarity_unavailable"}
    assert run.feature_summary_json["embedding_dependency"] is None


def test_candidate_mutation_during_semantic_scoring_blocks_stale_validation_run(
    session: Session,
) -> None:
    original_prompt = "Calculate two plus two."
    draft = generation_draft(session, candidate_json=valid_m1_candidate(original_prompt))
    add_published_question(session, draft=draft, prompt="Name the capital of France.")

    class CandidateMutatingGrader(PassingGrader):
        def semantic_similarity(
            self, query: str, comparisons: list[str]
        ) -> SemanticSimilarityResult:
            draft.candidate_json = {**draft.candidate_json, "prompt": "What is 9 + 9?"}
            session.flush()
            return semantic_result([0.1])

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=CandidateMutatingGrader()
    )

    finding = finding_by_code(run, "duplicate_semantic_check_unavailable")
    expected = fingerprint_prompt(original_prompt)
    assert run.status is ValidationRunStatus.BLOCKED
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

    first = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )
    second = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert first.status is ValidationRunStatus.PASSED
    assert first.run_number == 1
    assert first.findings == []
    assert second.run_number == 2
    assert draft.validation_runs == [first, second]


def test_valid_m2_candidate_normalizes_and_probes(session: Session) -> None:
    draft = generation_draft(
        session,
        allowed_question_types=["M2"],
        candidate_json=valid_m2_candidate(),
    )
    grader = PassingM2Grader()

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    assert run.status is ValidationRunStatus.PASSED
    assert grader.normalization_requests == [{"mathjson": ["Add", "x", 1], "variables": ["x"]}]
    assert grader.grade_requests[0][0] == "M2"
    assert grader.grade_requests[0][2] == {"mathjson": ["Add", "x", 1]}


def test_valid_e2_candidate_probes_every_accepted_form(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E2"], candidate_json=valid_e2_candidate()
    )
    grader = PassingE2Grader()
    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    duplicate_run = verification.run_candidate_verification(
        session, draft=duplicate_draft, grader_client=PassingE2Grader()
    )

    finding = next(item for item in duplicate_run.findings if item.code == "e2_forms_invalid")
    assert finding.evidence_json == {"reason": "normalized_duplicate", "accepted_form_count": 2}


@pytest.mark.parametrize("grader", [FailingE2Grader(), PartialE2Grader()])
def test_e2_grader_failure_is_safely_blocked(session: Session, grader: PassingE2Grader) -> None:
    failed_draft = generation_draft(
        session, allowed_question_types=["E2"], candidate_json=valid_e2_candidate()
    )
    failed_run = verification.run_candidate_verification(
        session, draft=failed_draft, grader_client=grader
    )

    finding = next(item for item in failed_run.findings if item.code == "e2_grader_probe_failed")
    assert finding.evidence_json == {"probe": "accepted_forms", "accepted_form_count": 1}
    assert "went" not in finding.remediation


def test_e2_schema_invalid_rules_do_not_call_the_grader(session: Session) -> None:
    candidate = valid_e2_candidate()
    candidate["rule_json"] = {"lemma": "go", "accepted_forms": []}
    draft = generation_draft(session, allowed_question_types=["E2"], candidate_json=candidate)
    grader = PassingE2Grader()

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_valid_e3_candidate_probes_prompt_and_reference_answers(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E3"], candidate_json=valid_e3_candidate()
    )
    grader = PassingE3Grader()

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(
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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_valid_e4_candidate_probes_every_evidence_phrase(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["E4"], candidate_json=valid_e4_candidate()
    )
    grader = PassingE4Grader()

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(
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

    run = verification.run_candidate_verification(
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

    run = verification.run_candidate_verification(
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

    run = verification.run_candidate_verification(
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
        verification.run_candidate_verification(
            session,
            draft=generation_draft(
                session, allowed_question_types=["E4"], candidate_json=candidate
            ),
            grader_client=PassingE4Grader(),
        ).status
        is ValidationRunStatus.PASSED
    )

    candidate["reading_material"] = "self-harm instructions"
    unsafe = verification.run_candidate_verification(
        session,
        draft=generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate),
        grader_client=PassingE4Grader(),
    )
    assert next(
        item for item in unsafe.findings if item.code == "unsafe_minor_content"
    ).evidence_json == {"category": "self_harm"}


def test_e4_normalized_duplicate_point_ids_are_blocked(session: Session) -> None:
    candidate = valid_e4_candidate()
    candidate["rule_json"]["scoring_points"][1]["id"] = " Reason "
    draft = generation_draft(session, allowed_question_types=["E4"], candidate_json=candidate)
    grader = PassingE4Grader()

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingE4Grader()
    )

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

    assert "policy_schema_invalid" in finding_codes(run)
    assert grader.grade_requests == []


def test_m2_normalizer_failure_is_safely_blocked(session: Session) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=FailingM2Normalizer()
    )

    finding = next(item for item in run.findings if item.code == "m2_mathjson_invalid")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"probe": "expected_mathjson"}
    assert "unsafe expression" not in finding.remediation


@pytest.mark.parametrize("grader", [FailingM2Grader(), PartialM2Grader()])
def test_m2_failed_probe_is_safely_blocked(session: Session, grader: PassingM2Grader) -> None:
    draft = generation_draft(
        session, allowed_question_types=["M2"], candidate_json=valid_m2_candidate()
    )

    run = verification.run_candidate_verification(session, draft=draft, grader_client=grader)

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=FloatingPointM2Grader()
    )

    assert run.status is ValidationRunStatus.PASSED


def test_invalid_m2_schema_preserves_policy_finding(session: Session) -> None:
    candidate = valid_m2_candidate()
    candidate["rule_json"] = {"variables": ["x"], "max_score": 4}
    draft = generation_draft(session, allowed_question_types=["M2"], candidate_json=candidate)

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingM2Grader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert finding_codes(run) == {"policy_schema_invalid"}


def test_inactive_revision_blocks_the_candidate(session: Session) -> None:
    draft = generation_draft(session, revision_status=CurriculumRevisionStatus.DRAFT)

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert "curriculum_revision_inactive" in finding_codes(run)


def test_candidate_for_a_different_objective_revision_is_blocked(session: Session) -> None:
    draft = generation_draft(session)
    draft.candidate_json["objective_revision_id"] = str(uuid4())

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert "curriculum_objective_mismatch" in finding_codes(run)


def test_candidate_difficulty_outside_objective_range_is_blocked(session: Session) -> None:
    draft = generation_draft(session)
    draft.job.curriculum_objective_revision.difficulty_max = 0.2
    draft.candidate_json["difficulty"] = 0.9

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert "difficulty_out_of_range" in finding_codes(run)


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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert {
        "question_type_not_allowed",
        "policy_schema_invalid",
        "m1_answer_invalid",
    } <= finding_codes(run)


def test_m1_grader_failure_is_blocked_without_exception_text(session: Session) -> None:
    draft = generation_draft(session)

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=FailingGrader()
    )

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=FailingGrader()
    )

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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=FailingGrader()
    )

    finding = next(finding for finding in run.findings if finding.code == "unsafe_minor_content")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"category": "adult_content"}
    assert "pornographic" not in str(finding.evidence_json)


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

    run = verification.run_candidate_verification(
        session, draft=duplicate, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert {"duplicate_normalized_prompt", "unsafe_minor_content"} <= finding_codes(run)
    unsafe_finding = next(
        finding for finding in run.findings if finding.code == "unsafe_minor_content"
    )
    assert unsafe_finding.evidence_json == {"category": "adult_content"}


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

    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    assert run.status is ValidationRunStatus.BLOCKED
    assert "prompt_or_explanation_invalid" in finding_codes(run)


def test_unexpected_validator_error_is_persisted_without_raw_exception(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = generation_draft(session)

    def raise_internal_error(*args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("internal secret diagnostic")

    monkeypatch.setattr(verification, "_evaluate_candidate", raise_internal_error)
    run = verification.run_candidate_verification(
        session, draft=draft, grader_client=PassingGrader()
    )

    finding = next(finding for finding in run.findings if finding.code == "validator_unavailable")
    assert run.status is ValidationRunStatus.BLOCKED
    assert finding.evidence_json == {"category": "internal_validation_error"}
    assert "secret" not in finding.remediation
