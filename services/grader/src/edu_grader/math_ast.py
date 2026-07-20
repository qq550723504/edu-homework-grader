from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

import sympy as sp
from pydantic import BaseModel, Field

from .mathjson import MathJsonValidationError, normalize_mathjson
from .models import Criterion, Feedback, GradingResult

_SYMBOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_NUMBER = re.compile(r"^-?(?:\d{1,64})(?:\.\d{1,32})?(?:/\d{1,64})?$")
MAX_DEPTH = 20
MAX_NODES = 100
MAX_ARGS = 12


class NumericGradeRequest(BaseModel):
    student_answer: str = Field(max_length=100)
    expected_answer: str = Field(max_length=100)
    tolerance: str = Field(default="0", max_length=100)
    max_score: float = Field(default=1, gt=0, le=100)


class ExpressionGradeRequest(BaseModel):
    student: dict[str, Any]
    expected: dict[str, Any]
    variables: list[str] = Field(default_factory=list, max_length=10)
    required_form: Literal["expanded"] | None = None
    form_score: float = Field(default=0, ge=0, le=100)
    max_score: float = Field(default=1, gt=0, le=100)


@dataclass
class _BuildContext:
    allowed_symbols: set[str]
    nodes: int = 0

    def use_node(self, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise ValueError(f"AST depth exceeds {MAX_DEPTH}")
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ValueError(f"AST node count exceeds {MAX_NODES}")


def _as_rational(value: str) -> sp.Rational:
    if not _NUMBER.fullmatch(value):
        raise ValueError("Number is outside the supported format or size limits")
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        if int(denominator) == 0:
            raise ValueError("Division by zero is not allowed")
        return sp.Rational(int(numerator), int(denominator))
    return sp.Rational(value)


def _require_dict(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise ValueError("Every AST node must be an object")
    return node


def build_expression(node: dict[str, Any], variables: list[str]) -> sp.Expr:
    allowed = set(variables)
    if any(not _SYMBOL_NAME.fullmatch(name) for name in allowed):
        raise ValueError("Variable names must be simple ASCII identifiers")
    return _build(_require_dict(node), _BuildContext(allowed), 0)


def _build(node: dict[str, Any], context: _BuildContext, depth: int) -> sp.Expr:
    context.use_node(depth)
    kind = node.get("type")

    if kind == "number":
        value = node.get("value")
        if not isinstance(value, str):
            raise ValueError("number.value must be a string")
        return _as_rational(value)

    if kind == "symbol":
        name = node.get("name")
        if not isinstance(name, str) or not _SYMBOL_NAME.fullmatch(name):
            raise ValueError("Invalid symbol name")
        if name not in context.allowed_symbols:
            raise ValueError(f"Symbol '{name}' is not allowed for this question")
        return sp.Symbol(name)

    if kind in {"add", "mul"}:
        args = node.get("args")
        if not isinstance(args, list) or not 2 <= len(args) <= MAX_ARGS:
            raise ValueError(f"{kind}.args must contain between 2 and {MAX_ARGS} nodes")
        expressions = [_build(_require_dict(arg), context, depth + 1) for arg in args]
        return (
            sp.Add(*expressions, evaluate=False)
            if kind == "add"
            else sp.Mul(*expressions, evaluate=False)
        )

    if kind == "neg":
        return -_build(_require_dict(node.get("arg")), context, depth + 1)

    if kind == "div":
        numerator = _build(_require_dict(node.get("numerator")), context, depth + 1)
        denominator = _build(_require_dict(node.get("denominator")), context, depth + 1)
        if denominator == 0:
            raise ValueError("Division by zero is not allowed")
        return numerator / denominator

    if kind == "pow":
        base = _build(_require_dict(node.get("base")), context, depth + 1)
        exponent_node = _require_dict(node.get("exponent"))
        exponent = _build(exponent_node, context, depth + 1)
        if not exponent.is_Integer or not -10 <= int(exponent) <= 10:
            raise ValueError("Only integer exponents between -10 and 10 are supported")
        return sp.Pow(base, exponent, evaluate=False)

    raise ValueError(f"Unsupported AST node type: {kind!r}")


def grade_numeric(request: NumericGradeRequest) -> GradingResult:
    if not request.student_answer.strip():
        return GradingResult(
            decision="auto_rejected",
            score=0.0,
            max_score=request.max_score,
            confidence=1.0,
            criteria=[
                Criterion(
                    code="numeric_value",
                    score=0.0,
                    max_score=request.max_score,
                    passed=False,
                    evidence="No numeric answer was provided.",
                )
            ],
            feedback=[Feedback(type="value", message="未提供数值答案。")],
        )
    try:
        student = Decimal(request.student_answer.strip())
        expected = Decimal(request.expected_answer.strip())
        tolerance = Decimal(request.tolerance.strip())
    except InvalidOperation as exc:
        raise ValueError("Numeric answers and tolerance must be valid decimal values") from exc

    if not student.is_finite() or not expected.is_finite() or not tolerance.is_finite():
        raise ValueError("NaN and infinite values are not supported")
    if tolerance < 0:
        raise ValueError("Tolerance cannot be negative")

    matched = abs(student - expected) <= tolerance
    score = request.max_score if matched else 0.0
    return GradingResult(
        decision="auto_accepted" if matched else "auto_rejected",
        score=score,
        max_score=request.max_score,
        confidence=1.0,
        criteria=[
            Criterion(
                code="numeric_value",
                score=score,
                max_score=request.max_score,
                passed=matched,
                evidence=f"Absolute error is {abs(student - expected)}; tolerance is {tolerance}.",
            )
        ],
        feedback=[] if matched else [Feedback(type="value", message="数值不在允许误差范围内。")],
    )


def grade_expression(request: ExpressionGradeRequest) -> GradingResult:
    if request.form_score > request.max_score:
        raise ValueError("form_score cannot exceed max_score")

    student = build_expression(request.student, request.variables)
    expected = build_expression(request.expected, request.variables)

    difference = sp.cancel(sp.together(student - expected))
    equivalent = difference == 0
    form_ok = request.required_form is None or sp.expand(student) == student

    correctness_max = request.max_score - request.form_score
    correctness_score = correctness_max if equivalent else 0.0
    awarded_form_score = request.form_score if equivalent and form_ok else 0.0
    total = correctness_score + awarded_form_score

    if equivalent and form_ok:
        decision = "auto_accepted"
    elif equivalent:
        decision = "partial"
    else:
        decision = "auto_rejected"

    feedback: list[Feedback] = []
    if not equivalent:
        feedback.append(Feedback(type="correctness", message="表达式与标准答案不等价。"))
    elif not form_ok:
        feedback.append(Feedback(type="form", message="结果等价，但未按题目要求展开。"))

    criteria = [
        Criterion(
            code="algebraic_equivalence",
            score=correctness_score,
            max_score=correctness_max,
            passed=equivalent,
            evidence=(
                "The bounded symbolic difference simplified to zero."
                if equivalent
                else "The bounded symbolic difference did not simplify to zero."
            ),
        )
    ]
    if request.form_score > 0:
        criteria.append(
            Criterion(
                code="required_form",
                score=awarded_form_score,
                max_score=request.form_score,
                passed=form_ok,
                evidence=(
                    "The answer is in the required expanded form."
                    if form_ok
                    else "The answer is algebraically correct but not expanded."
                ),
            )
        )

    return GradingResult(
        decision=decision,
        score=total,
        max_score=request.max_score,
        confidence=0.99,
        criteria=criteria,
        feedback=feedback,
    )


def grade_mathjson_expression(
    *,
    student_mathjson: object,
    expected_mathjson: object,
    variables: list[str],
    required_form: Literal["expanded"] | None,
    form_score: float,
    max_score: float,
) -> GradingResult:
    if form_score > max_score:
        raise ValueError("form_score cannot exceed max_score")
    try:
        student_ast = normalize_mathjson(student_mathjson, variables)
        expected_ast = normalize_mathjson(expected_mathjson, variables)
    except MathJsonValidationError as error:
        return mathjson_review_result(error, max_score)

    return grade_normalized_expression(
        student_ast=student_ast,
        expected_ast=expected_ast,
        variables=variables,
        required_form=required_form,
        form_score=form_score,
        max_score=max_score,
    )


def grade_normalized_expression(
    *,
    student_ast: dict[str, object],
    expected_ast: dict[str, object],
    variables: list[str],
    required_form: Literal["expanded"] | None,
    form_score: float,
    max_score: float,
) -> GradingResult:
    if form_score > max_score:
        raise ValueError("form_score cannot exceed max_score")

    student = build_expression(student_ast, variables)
    expected = build_expression(expected_ast, variables)
    equivalent = sp.cancel(sp.together(student - expected)) == 0
    form_ok = required_form is None or is_expanded_ast(student_ast)
    correctness_max = max_score - form_score
    correctness_score = correctness_max if equivalent else 0.0
    awarded_form_score = form_score if equivalent and form_ok else 0.0
    total = correctness_score + awarded_form_score

    criteria = [
        Criterion(
            code="algebraic_equivalence",
            score=correctness_score,
            max_score=correctness_max,
            passed=equivalent,
            evidence=(
                "The bounded symbolic difference simplified to zero."
                if equivalent
                else "The bounded symbolic difference did not simplify to zero."
            ),
        )
    ]
    feedback: list[Feedback] = []
    if not equivalent:
        feedback.append(Feedback(type="correctness", message="表达式与标准答案不等价。"))
    elif not form_ok:
        feedback.append(Feedback(type="form", message="结果等价，但未按题目要求展开。"))
    if form_score > 0:
        criteria.append(
            Criterion(
                code="required_form",
                score=awarded_form_score,
                max_score=form_score,
                passed=form_ok,
                evidence=(
                    "The answer is in the required expanded form."
                    if form_ok
                    else "The answer is algebraically correct but not expanded."
                ),
            )
        )

    return GradingResult(
        decision="auto_accepted"
        if equivalent and form_ok
        else "partial"
        if equivalent
        else "auto_rejected",
        score=total,
        max_score=max_score,
        confidence=0.99,
        criteria=criteria,
        feedback=feedback,
    )


def is_expanded_ast(node: dict[str, object]) -> bool:
    kind = node["type"]
    if kind == "number" or kind == "symbol":
        return True
    if kind == "neg":
        return is_expanded_ast(_node(node["arg"]))
    if kind == "div":
        return is_expanded_ast(_node(node["numerator"])) and is_expanded_ast(
            _node(node["denominator"])
        )
    if kind == "pow":
        base = _node(node["base"])
        return base["type"] != "add" and is_expanded_ast(base)
    if kind == "mul":
        arguments = _nodes(node["args"])
        return all(
            argument["type"] != "add" and is_expanded_ast(argument) for argument in arguments
        )
    if kind == "add":
        return all(is_expanded_ast(argument) for argument in _nodes(node["args"]))
    raise ValueError(f"Unsupported AST node type: {kind!r}")


def mathjson_review_result(error: MathJsonValidationError, max_score: float) -> GradingResult:
    return GradingResult(
        decision="needs_review",
        score=0,
        max_score=max_score,
        confidence=0,
        requires_review=True,
        criteria=[
            Criterion(
                code=error.code,
                score=0,
                max_score=max_score,
                passed=False,
                evidence=str(error),
            )
        ],
        feedback=[Feedback(type="math_input", message="该数学表达式需要教师复核。")],
    )


def _node(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("AST node must be an object")
    return value


def _nodes(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(node, dict) for node in value):
        raise ValueError("AST arguments must be objects")
    return value
