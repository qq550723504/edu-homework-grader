#!/usr/bin/env python3
"""One-shot sanitization for PR #107; removed before review."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = ROOT / "apps/api/src/edu_grader_api/services/math_semantics.py"
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '_SUPPORTED_EXPRESSION_OPERATORS = frozenset(\n    {"Add", "Multiply", "Negate", "Divide", "Rational", "Power"}\n)\n',
    '_SUPPORTED_EXPRESSION_OPERATORS = frozenset(\n    {"Add", "Multiply", "Negate", "Divide", "Rational", "Power"}\n)\n_KNOWN_OPERATORS = (\n    _EQUATION_OPERATORS\n    | _SOLUTION_SET_OPERATORS\n    | _DOMAIN_OPERATORS\n    | _ROOT_RISK_OPERATORS\n    | _INSUFFICIENT_CONDITION_OPERATORS\n    | _SUPPORTED_EXPRESSION_OPERATORS\n)\n',
    "known operator catalogue",
)
text = replace_once(
    text,
    '            trigger_operator=operator if isinstance(operator, str) else "object",\n',
    '            trigger_operator=_public_trigger_operator(operator),\n',
    "M1 operator sanitization",
)
text = replace_once(
    text,
    '    if operator not in _SUPPORTED_EXPRESSION_OPERATORS:\n        return "unsupported_structure", operator\n',
    '    if operator not in _SUPPORTED_EXPRESSION_OPERATORS:\n        return "unsupported_structure", _public_trigger_operator(operator)\n',
    "M2 operator sanitization",
)
text = replace_once(
    text,
    '\ndef _container_name(value: object) -> str:\n',
    '\ndef _public_trigger_operator(operator: object) -> str:\n'
    '    if isinstance(operator, str) and operator in _KNOWN_OPERATORS:\n'
    '        return operator\n'
    '    return "unknown_operator"\n'
    '\n\ndef _container_name(value: object) -> str:\n',
    "public operator helper",
)
path.write_text(text, encoding="utf-8")

path = ROOT / "apps/api/tests/test_math_semantics.py"
tests = path.read_text(encoding="utf-8")
tests = replace_once(
    tests,
    '    assert "private_symbol" not in persisted\n    assert "SecretOperator" in persisted\n    assert json.dumps(expected) not in persisted\n',
    '    assert "private_symbol" not in persisted\n'
    '    assert "SecretOperator" not in persisted\n'
    '    assert evaluation.trigger_operator == "unknown_operator"\n'
    '    assert json.dumps(expected) not in persisted\n',
    "unknown operator test",
)
path.write_text(tests, encoding="utf-8")
