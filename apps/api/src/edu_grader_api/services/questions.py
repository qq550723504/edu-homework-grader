from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    AuditLog,
    GradingPolicy,
    Question,
    QuestionTestCase,
    QuestionTestCaseRun,
    QuestionTestRun,
    QuestionVersion,
    TestRunStatus,
    VersionStatus,
    utc_now,
)
from ..policies import POLICY_SCHEMAS, validate_policy


class QuestionVersionAccessError(PermissionError):
    """Raised when an actor is not allowed to modify a question version."""


class QuestionVersionStateError(ValueError):
    """Raised when an operation is invalid for the version lifecycle state."""


class PublishConflict(QuestionVersionStateError):
    """Raised when a draft does not satisfy the publication gate."""


class QuestionPolicyValidationError(ValueError):
    """Raised when a question rule does not conform to its policy schema."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("question rule is invalid")
        self.errors = errors


@dataclass(frozen=True)
class GradeResult:
    decision: str
    score: float
    evidence: dict[str, object]
    grader_version: str


class GraderClient(Protocol):
    def grade(
        self,
        question_type: str,
        rule_json: dict[str, object],
        answer_json: dict[str, object],
    ) -> GradeResult: ...


def create_question(
    session: Session,
    *,
    tenant_id: UUID,
    actor_user_id: UUID,
    title: str,
    prompt: str,
    question_type: str,
    policy_version: str,
    rule_json: dict[str, object],
) -> QuestionVersion:
    """Create a tenant question and its first mutable version."""

    errors = validate_policy(question_type, policy_version, rule_json)
    if errors:
        raise QuestionPolicyValidationError(errors)

    policy = session.scalar(
        select(GradingPolicy).where(
            GradingPolicy.question_type == question_type,
            GradingPolicy.policy_version == policy_version,
            GradingPolicy.retired_at.is_(None),
        )
    )
    if policy is None:
        policy = GradingPolicy(
            question_type=question_type,
            policy_version=policy_version,
            json_schema=dict(POLICY_SCHEMAS[(question_type, policy_version)]),
        )
        session.add(policy)
        session.flush()

    question = Question(tenant_id=tenant_id, created_by_user_id=actor_user_id, title=title)
    session.add(question)
    session.flush()
    version = QuestionVersion(
        question_id=question.id,
        version_number=1,
        status=VersionStatus.DRAFT,
        prompt=prompt,
        question_type=question_type,
        grading_policy_id=policy.id,
        rule_json=rule_json,
        created_by_user_id=actor_user_id,
    )
    session.add(version)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            event_type="question.created",
            target_type="question",
            target_id=question.id,
            metadata_json={"title": title, "version_number": 1},
        )
    )
    return version


def create_successor_draft(
    session: Session,
    published_version: QuestionVersion,
    *,
    actor_user_id: UUID,
) -> QuestionVersion:
    """Copy a published version into the next immutable-history draft."""

    _require_author(session, published_version, actor_user_id)
    if published_version.status is not VersionStatus.PUBLISHED:
        raise QuestionVersionStateError("only published versions can have a successor draft")

    latest_version_number = session.scalar(
        select(func.max(QuestionVersion.version_number)).where(
            QuestionVersion.question_id == published_version.question_id
        )
    )
    successor = QuestionVersion(
        question_id=published_version.question_id,
        version_number=(latest_version_number or 0) + 1,
        status=VersionStatus.DRAFT,
        prompt=published_version.prompt,
        question_type=published_version.question_type,
        grading_policy_id=published_version.grading_policy_id,
        rule_json=published_version.rule_json.copy(),
        created_by_user_id=actor_user_id,
    )
    session.add(successor)
    session.flush()
    for test_case in published_version.test_cases:
        session.add(
            QuestionTestCase(
                question_version_id=successor.id,
                category=test_case.category,
                answer_json=test_case.answer_json.copy(),
                expected_decision=test_case.expected_decision,
                expected_score=test_case.expected_score,
                expected_evidence_json=test_case.expected_evidence_json.copy(),
            )
        )
    return successor


def update_draft(
    session: Session,
    draft: QuestionVersion,
    *,
    actor_user_id: UUID,
    prompt: str,
    rule_json: dict[str, object] | None = None,
) -> None:
    """Update mutable draft content without allowing history rewrites."""

    _require_author(session, draft, actor_user_id)
    if draft.status is not VersionStatus.DRAFT:
        raise QuestionVersionStateError("only draft versions can be edited")
    if rule_json is not None:
        policy = session.get(GradingPolicy, draft.grading_policy_id)
        if policy is None:
            raise QuestionVersionStateError("grading policy is unavailable")
        errors = validate_policy(policy.question_type, policy.policy_version, rule_json)
        if errors:
            raise QuestionPolicyValidationError(errors)
        draft.rule_json = rule_json
    draft.prompt = prompt
    session.add(draft)


def run_question_tests(
    session: Session,
    draft: QuestionVersion,
    *,
    trigger: str,
    grader_client: GraderClient,
) -> QuestionTestRun:
    """Run every version-bound test case and persist an auditable result."""

    if draft.status is not VersionStatus.DRAFT:
        raise QuestionVersionStateError("only draft versions can run tests")

    test_cases = list(
        session.scalars(
            select(QuestionTestCase)
            .where(QuestionTestCase.question_version_id == draft.id)
            .order_by(QuestionTestCase.category)
        )
    )
    test_run = QuestionTestRun(
        question_version_id=draft.id,
        grader_version="not-run",
        trigger=trigger,
        status=TestRunStatus.FAILED,
    )
    session.add(test_run)
    session.flush()

    grader_error = False
    for test_case in test_cases:
        try:
            result = grader_client.grade(
                draft.question_type, draft.rule_json, test_case.answer_json
            )
        except Exception as error:  # Grader failures must remain visible in run history.
            grader_error = True
            session.add(
                QuestionTestCaseRun(
                    question_test_run_id=test_run.id,
                    question_test_case_id=test_case.id,
                    decision="grading_error",
                    score=0,
                    evidence_json={},
                    passed=False,
                    error_detail=str(error),
                )
            )
            continue

        test_run.grader_version = result.grader_version
        passed = (
            result.decision == test_case.expected_decision
            and result.score == test_case.expected_score
            and result.evidence == test_case.expected_evidence_json
        )
        session.add(
            QuestionTestCaseRun(
                question_test_run_id=test_run.id,
                question_test_case_id=test_case.id,
                decision=result.decision,
                score=result.score,
                evidence_json=result.evidence,
                passed=passed,
            )
        )

    session.flush()
    case_runs = list(test_run.case_runs)
    policy = session.get(GradingPolicy, draft.grading_policy_id)
    policy_version = policy.policy_version if policy is not None else None
    missing_categories = _required_test_categories(draft.question_type, policy_version) - {
        test_case.category for test_case in test_cases
    }
    if grader_error:
        test_run.status = TestRunStatus.GRADING_ERROR
        test_run.failure_summary = "the grader failed for one or more test cases"
    elif missing_categories:
        test_run.status = TestRunStatus.FAILED
        test_run.failure_summary = (
            f"missing required test categories: {', '.join(sorted(missing_categories))}"
        )
    elif not case_runs or not all(case_run.passed for case_run in case_runs):
        test_run.status = TestRunStatus.FAILED
        test_run.failure_summary = "one or more test cases did not match their expectation"
    else:
        test_run.status = TestRunStatus.PASSED
    test_run.finished_at = utc_now()
    session.add(test_run)
    question = session.get(Question, draft.question_id)
    if question is not None:
        session.add(
            AuditLog(
                tenant_id=question.tenant_id,
                actor_user_id=draft.created_by_user_id,
                event_type="question.test_run",
                target_type="question_version",
                target_id=draft.id,
                metadata_json={"test_run_id": str(test_run.id), "status": test_run.status.value},
            )
        )
    return test_run


def publish_question_version(
    session: Session,
    draft: QuestionVersion,
    *,
    actor_user_id: UUID,
) -> QuestionVersion:
    """Publish only the current draft after a complete passing test run."""

    _require_author(session, draft, actor_user_id)
    if draft.status is not VersionStatus.DRAFT:
        raise PublishConflict("only draft versions can be published")

    latest_run = session.scalar(
        select(QuestionTestRun)
        .where(QuestionTestRun.question_version_id == draft.id)
        .order_by(QuestionTestRun.started_at.desc())
        .limit(1)
    )
    if latest_run is None or latest_run.status is not TestRunStatus.PASSED:
        raise PublishConflict("a complete passing test run is required before publishing")

    draft.status = VersionStatus.PUBLISHED
    draft.published_by_user_id = actor_user_id
    draft.published_at = utc_now()
    question = session.get(Question, draft.question_id)
    if question is not None:
        session.add(
            AuditLog(
                tenant_id=question.tenant_id,
                actor_user_id=actor_user_id,
                event_type="question.published",
                target_type="question_version",
                target_id=draft.id,
                metadata_json={"version_number": draft.version_number},
            )
        )
    session.add(draft)
    return draft


def _required_test_categories(question_type: str, policy_version: str | None = None) -> set[str]:
    required = {"correct", "incorrect", "empty", "boundary"}
    if question_type == "M2":
        required.add("invalid_ast")
        if policy_version == "2":
            required.update({"invalid_mathjson", "resource_limit"})
    if question_type == "E3":
        required.add("grammar_feedback")
    if question_type == "E4":
        required.add("needs_review")
    return required


def _require_author(session: Session, version: QuestionVersion, actor_user_id: UUID) -> None:
    author_id = session.scalar(
        select(Question.created_by_user_id).where(Question.id == version.question_id)
    )
    if author_id != actor_user_id:
        raise QuestionVersionAccessError("only the original author can edit this question")
