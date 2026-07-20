import pytest

from edu_grader.math_ast import (
    ExpressionGradeRequest,
    NumericGradeRequest,
    build_expression,
    grade_expression,
    grade_mathjson_expression,
    grade_numeric,
    is_expanded_ast,
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


def test_blank_numeric_answer_is_safely_rejected() -> None:
    result = grade_numeric(
        NumericGradeRequest(student_answer="   ", expected_answer="5", tolerance="0")
    )

    assert result.decision == "auto_rejected"
    assert result.score == 0
    assert result.criteria[0].code == "numeric_value"


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


def test_mathjson_symbolic_denominator_requires_review() -> None:
    result = grade_mathjson_expression(
        student_mathjson=["Divide", 1, "x"],
        expected_mathjson=["Divide", 1, "x"],
        variables=["x"],
        required_form=None,
        form_score=0,
        max_score=1,
    )

    assert result.decision == "needs_review"
    assert result.requires_review is True
    assert result.criteria[0].code == "symbolic_denominator"


def test_mathjson_unsupported_operator_requires_review() -> None:
    result = grade_mathjson_expression(
        student_mathjson=["Assign", "x", 1],
        expected_mathjson=["Add", "x", 1],
        variables=["x"],
        required_form=None,
        form_score=0,
        max_score=1,
    )

    assert result.decision == "needs_review"
    assert result.criteria[0].code == "unsupported_operator"


def test_product_with_additive_factor_is_not_expanded() -> None:
    assert (
        is_expanded_ast(
            {
                "type": "mul",
                "args": [number("2"), {"type": "add", "args": [symbol("x"), number("3")]}],
            }
        )
        is False
    )
