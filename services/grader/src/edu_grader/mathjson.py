from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any


MAX_DEPTH = 20
MAX_NODES = 100
MAX_ARGS = 12
_SYMBOL = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_NUMBER = re.compile(r"^-?(?:\d{1,64})(?:\.\d{1,32})?$")
_INTEGER = re.compile(r"^-?\d+$")


class MathJsonValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class _Context:
    allowed_symbols: set[str]
    nodes: int = 0

    def use_node(self, depth: int) -> None:
        if depth > MAX_DEPTH:
            raise MathJsonValidationError("depth_limit", f"expression depth exceeds {MAX_DEPTH}")
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise MathJsonValidationError(
                "node_limit", f"expression contains more than {MAX_NODES} nodes"
            )


def normalize_mathjson(value: object, variables: list[str]) -> dict[str, object]:
    if any(not _SYMBOL.fullmatch(variable) for variable in variables):
        raise MathJsonValidationError("invalid_variable", "variables must be ASCII identifiers")
    return _normalize(value, _Context(set(variables)), depth=0)


def _normalize(value: object, context: _Context, depth: int) -> dict[str, object]:
    context.use_node(depth)
    if isinstance(value, bool):
        raise MathJsonValidationError(
            "unsupported_representation", "boolean values are not expressions"
        )
    if isinstance(value, int | float):
        return _number_node(value)
    if isinstance(value, str):
        if value in {"NaN", "+Infinity", "-Infinity"}:
            raise MathJsonValidationError("non_finite_number", "numbers must be finite")
        if _NUMBER.fullmatch(value):
            return _number_node(value)
        if value[:1] in {"-", *"0123456789"}:
            return _number_node(value)
        if value in context.allowed_symbols:
            return {"type": "symbol", "name": value}
        raise MathJsonValidationError("unknown_symbol", "symbol is not allowed for this question")
    if isinstance(value, dict):
        raise MathJsonValidationError(
            "unsupported_representation", "MathJSON object forms are not accepted"
        )
    if not isinstance(value, list) or not value:
        raise MathJsonValidationError(
            "unsupported_representation", "expression must be a MathJSON shorthand"
        )

    operator = value[0]
    if not isinstance(operator, str):
        raise MathJsonValidationError("invalid_operator", "MathJSON operator must be a string")
    arguments = value[1:]
    if operator in {"Add", "Multiply"}:
        _require_arity(operator, arguments, minimum=2, maximum=MAX_ARGS)
        return {
            "type": "add" if operator == "Add" else "mul",
            "args": [_normalize(argument, context, depth + 1) for argument in arguments],
        }
    if operator == "Negate":
        _require_arity(operator, arguments, minimum=1, maximum=1)
        return {"type": "neg", "arg": _normalize(arguments[0], context, depth + 1)}
    if operator == "Divide":
        _require_arity(operator, arguments, minimum=2, maximum=2)
        numerator = _normalize(arguments[0], context, depth + 1)
        denominator = _normalize(arguments[1], context, depth + 1)
        if denominator["type"] != "number":
            raise MathJsonValidationError(
                "symbolic_denominator", "expressions with symbolic denominators require review"
            )
        if _is_zero(str(denominator["value"])):
            raise MathJsonValidationError("zero_denominator", "division by zero is not allowed")
        return {"type": "div", "numerator": numerator, "denominator": denominator}
    if operator == "Rational":
        _require_arity(operator, arguments, minimum=2, maximum=2)
        numerator = _normalize(arguments[0], context, depth + 1)
        denominator = _normalize(arguments[1], context, depth + 1)
        if numerator["type"] != "number" or denominator["type"] != "number":
            raise MathJsonValidationError("invalid_rational", "Rational operands must be numbers")
        numerator_value = str(numerator["value"])
        denominator_value = str(denominator["value"])
        if not _INTEGER.fullmatch(numerator_value) or not _INTEGER.fullmatch(denominator_value):
            raise MathJsonValidationError("invalid_rational", "Rational operands must be integers")
        if _is_zero(denominator_value):
            raise MathJsonValidationError("zero_denominator", "division by zero is not allowed")
        return {"type": "number", "value": f"{numerator_value}/{denominator_value}"}
    if operator == "Power":
        _require_arity(operator, arguments, minimum=2, maximum=2)
        base = _normalize(arguments[0], context, depth + 1)
        exponent = _normalize(arguments[1], context, depth + 1)
        if exponent["type"] != "number" or not _INTEGER.fullmatch(str(exponent["value"])):
            raise MathJsonValidationError("invalid_exponent", "exponents must be integers")
        exponent_value = int(str(exponent["value"]))
        if not -10 <= exponent_value <= 10:
            raise MathJsonValidationError(
                "exponent_out_of_range", "exponents must be between -10 and 10"
            )
        if exponent_value < 0 and base["type"] != "number":
            raise MathJsonValidationError(
                "symbolic_denominator", "negative powers of symbolic expressions require review"
            )
        return {"type": "pow", "base": base, "exponent": exponent}
    raise MathJsonValidationError("unsupported_operator", f"operator {operator!r} is not supported")


def _number_node(value: int | float | str) -> dict[str, object]:
    if isinstance(value, float) and not math.isfinite(value):
        raise MathJsonValidationError("non_finite_number", "numbers must be finite")
    text = str(value)
    if not _NUMBER.fullmatch(text):
        raise MathJsonValidationError(
            "number_limit", "number exceeds the supported precision limits"
        )
    return {"type": "number", "value": text}


def _require_arity(operator: str, arguments: list[Any], *, minimum: int, maximum: int) -> None:
    if not minimum <= len(arguments) <= maximum:
        raise MathJsonValidationError(
            "invalid_arity", f"{operator} requires between {minimum} and {maximum} operands"
        )


def _is_zero(value: str) -> bool:
    return int(value) == 0 if _INTEGER.fullmatch(value) else float(value) == 0
