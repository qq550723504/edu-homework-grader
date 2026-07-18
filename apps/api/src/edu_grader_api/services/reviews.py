from sqlalchemy.orm import Session

from ..models import GradingRun, ReviewReason, ReviewTask, ReviewTaskStatus


def create_review_task_for_run(session: Session, run: GradingRun) -> ReviewTask:
    task = ReviewTask(
        attempt_answer=run.attempt_answer,
        grading_run=run,
        reason=(
            ReviewReason.NEEDS_REVIEW if run.requires_review else ReviewReason.AUTO_CONFIRMATION
        ),
        status=ReviewTaskStatus.OPEN,
        active_key="open",
        version=0,
    )
    session.add(task)
    return task
