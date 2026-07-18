import pytest

from edu_grader.math_ast import (
    ExpressionGradeRequest,
    NumericGradeRequest,
    build_expression,
    grade_expression,
    grade_numeric,
)


def number(value: str) -> dict[str, str]:
    return {"type": "number", "value": value}


def symbol(name: str) -> dict[str, str]:
    return {"type": "symbol", "name": name}


def test_numeric_tolerance() -> None:
    result = grade_numeric(
        NumericGradeRequest(
            student_answer="3.1415",
            expected_answer="3.14",
            tolerance="0.002",
            max_score=2,
        )
    )

    assert result.decision == "auto_accepted"
    assert result.score == 2


def test_expression_equivalence() -> None:
    student = {
        "type": "add",
        "args": [
            {"type": "mul", "args": [number("2"), symbol("x")]},
            number("6"),
        ],
    }
    expected = {
        "type": "mul",
        "args": [
            number("2"),
            {"type": "add", "args": [symbol("x"), number("3")]},
        ],
    }

    result = grade_expression(
        ExpressionGradeRequest(
            student=student,
            expected=expected,
            variables=["x"],
            max_score=5,
        )
    )

    assert result.decision == "auto_accepted"
    assert result.score == 5


def test_required_expanded_form_can_receive_partial_credit() -> None:
    student = {
        "type": "mul",
        "args": [
            number("2"),
            {"type": "add", "args": [symbol("x"), number("3")]},
        ],
    }
    expected = {
        "type": "add",
        "args": [
            {"type": "mul", "args": [number("2"), symbol("x")]},
            number("6"),
        ],
    }

    result = grade_expression(
        ExpressionGradeRequest(
            student=student,
            expected=expected,
            variables=["x"],
            required_form="expanded",
            form_score=1,
            max_score=5,
        )
    )

    assert result.decision == "partial"
    assert result.score == 4


def test_unknown_symbol_is_rejected() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        build_expression(symbol("z"), variables=["x"])


def test_exponent_limit_is_enforced() -> None:
    expression = {
        "type": "pow",
        "base": symbol("x"),
        "exponent": number("100"),
    }

    with pytest.raises(ValueError, match="between -10 and 10"):
        build_expression(expression, variables=["x"])
