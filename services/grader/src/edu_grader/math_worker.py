from __future__ import annotations

from typing import TYPE_CHECKING

from .math_ast import grade_normalized_expression
from .models import GradingResult

if TYPE_CHECKING:
    from .execution import MathExecutionLimits


def grade_in_worker(request: dict[str, object], limits: MathExecutionLimits) -> GradingResult:
    _apply_resource_limits(limits)
    return grade_normalized_expression(
        student_ast=_ast(request["student_ast"]),
        expected_ast=_ast(request["expected_ast"]),
        variables=list(request["variables"]),
        required_form=request["required_form"],
        form_score=float(request["form_score"]),
        max_score=float(request["max_score"]),
    )


def _apply_resource_limits(limits: MathExecutionLimits) -> None:
    try:
        import resource
    except ImportError:
        return
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))


def _ast(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("worker requires normalized AST objects")
    return value
