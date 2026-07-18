from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
from multiprocessing.connection import Connection
from .models import Criterion, Feedback, GradingResult


@dataclass(frozen=True)
class MathExecutionLimits:
    cpu_seconds: int
    memory_bytes: int
    timeout_seconds: float


def run_math_expression(request: dict[str, object], limits: MathExecutionLimits) -> GradingResult:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_run_worker, args=(sender, request, limits))
    process.start()
    sender.close()
    try:
        if not _join_worker(process, limits.timeout_seconds):
            process.terminate()
            process.join()
            return _review_result("execution_timeout", "数学判分超过时间限制。", request)
        if receiver.poll():
            return GradingResult.model_validate(receiver.recv())
        return _review_result("execution_resource_limit", "数学判分未能在资源限制内完成。", request)
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
            process.join()


def _join_worker(process: multiprocessing.Process, timeout_seconds: float) -> bool:
    process.join(timeout_seconds)
    return not process.is_alive()


def _run_worker(
    sender: Connection, request: dict[str, object], limits: MathExecutionLimits
) -> None:
    from .math_worker import grade_in_worker

    try:
        sender.send(grade_in_worker(request, limits).model_dump())
    except Exception:
        sender.send(_review_result("execution_failure", "数学判分执行失败。", request).model_dump())
    finally:
        sender.close()


def _review_result(code: str, message: str, request: dict[str, object]) -> GradingResult:
    max_score = float(request.get("max_score", 1))
    return GradingResult(
        decision="needs_review",
        score=0,
        max_score=max_score,
        confidence=0,
        requires_review=True,
        criteria=[
            Criterion(code=code, score=0, max_score=max_score, passed=False, evidence=message)
        ],
        feedback=[Feedback(type="execution", message=message)],
    )
