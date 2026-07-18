from edu_grader_api.models import (
    Base,
    GradePublication,
    ReviewDecision,
    ReviewReason,
    ReviewTask,
    ReviewTaskStatus,
)


def test_review_domain_exposes_manual_and_deterministic_queue_reasons() -> None:
    assert ReviewReason.NEEDS_REVIEW.value == "needs_review"
    assert ReviewReason.AUTO_CONFIRMATION.value == "auto_confirmation"
    assert ReviewTaskStatus.OPEN.value == "open"


def test_review_domain_registers_task_decision_and_publication_tables() -> None:
    assert ReviewTask.__tablename__ in Base.metadata.tables
    assert ReviewDecision.__tablename__ in Base.metadata.tables
    assert GradePublication.__tablename__ in Base.metadata.tables
