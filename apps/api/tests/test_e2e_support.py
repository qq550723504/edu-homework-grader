from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from edu_grader_api.db import Base
from edu_grader_api.e2e_support import (
    AI_REVIEW_JOB_KEY,
    DeterministicE2EGraderClient,
    DeterministicM2Client,
    seed_demo_assignment,
)
from edu_grader_api.models import (
    GeneratedQuestionDraft,
    GeneratedQuestionDraftRevision,
    GenerationJob,
    GenerationValidationRun,
)


def test_e2e_grader_evaluates_m1_numeric_answers_against_the_rule() -> None:
    client = DeterministicM2Client("unused")

    accepted = client.grade(
        "M1", {"expected": 5}, {"format": "text-v1", "text": "5"}, policy_version="1"
    )
    rejected = client.grade(
        "M1", {"expected": 5}, {"format": "text-v1", "text": "4"}, policy_version="1"
    )

    assert (accepted.decision, accepted.score) == ("auto_accepted", 1.0)
    assert (rejected.decision, rejected.score) == ("auto_rejected", 0.0)


def test_e2e_grader_covers_english_authoring_policy_boundaries() -> None:
    client = DeterministicE2EGraderClient("unused")

    e1_accepted = client.grade(
        "E1",
        {"accepted_answers": ["cat"], "max_score": 1},
        {"format": "text-v1", "text": "cat"},
        policy_version="2",
    )
    e2_rejected = client.grade(
        "E2",
        {"accepted_forms": ["went"], "max_score": 1},
        {"format": "text-v1", "text": "go"},
        policy_version="1",
    )
    e3_review = client.grade(
        "E3",
        {"grammar_feedback_required": True, "max_score": 1},
        {"format": "text-v1", "text": "I go."},
        policy_version="1",
    )
    e4_matched = client.grade(
        "E4",
        {
            "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
            "max_score": 1,
        },
        {"format": "text-v1", "text": "The bridge closed."},
        policy_version="2",
    )
    e4_unmatched = client.grade(
        "E4",
        {
            "scoring_points": [{"id": "cause", "evidence_phrases": ["bridge closed"], "score": 1}],
            "max_score": 1,
        },
        {"format": "text-v1", "text": "The road opened."},
        policy_version="2",
    )

    assert (e1_accepted.decision, e1_accepted.score) == ("auto_accepted", 1.0)
    assert (e2_rejected.decision, e2_rejected.score) == ("auto_rejected", 0.0)
    assert (e3_review.decision, e3_review.score) == ("needs_review", 0.0)
    assert (e4_matched.decision, e4_matched.score) == ("needs_review", 1.0)
    assert (e4_unmatched.decision, e4_unmatched.score) == ("needs_review", 0.0)
    assert e4_matched.evidence["criteria"] == [
        {"code": "cause", "passed": True, "score": 1.0, "max_score": 1.0}
    ]


def test_ai_review_seed_is_idempotent() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            seed_demo_assignment(session)
            seed_demo_assignment(session)

            job_ids = session.scalars(
                select(GenerationJob.id).where(GenerationJob.idempotency_key == AI_REVIEW_JOB_KEY)
            ).all()
            draft_count = session.scalar(select(func.count()).select_from(GeneratedQuestionDraft))
            revision_count = session.scalar(
                select(func.count()).select_from(GeneratedQuestionDraftRevision)
            )
            validation_count = session.scalar(
                select(func.count()).select_from(GenerationValidationRun)
            )

            assert len(job_ids) == 1
            assert draft_count == 2
            assert revision_count == 3
            assert validation_count == 2
    finally:
        engine.dispose()
