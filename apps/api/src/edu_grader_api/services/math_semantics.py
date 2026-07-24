"""Versioned, de-identified support matrix for generated mathematics candidates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

MATH_SEMANTICS_RULESET_VERSION = "math-semantics-v1"

SupportStatus = Literal["supported", "blocked", "not_applicable", "invalid"]
SemanticClass = Literal[
    "single_numeric_value",
    "expression_equivalence",
    "equation_or_inequality",
    "multiple_solution_set",
    "domain_restriction",
    "extraneous_or_missing_root_risk",
    "insufficient_conditions",
    "unsupported_structure",
    "not_applicable",
]

_EQUATION_OPERATORS = frozenset(
    {
        "Equal",
        "NotEqual",
        "Less",
        "LessEqual",
        "Greater",
        "GreaterEqual",
        "Equation",
        "Inequality",
        "Solve",
        "SolveEquation",
        "Roots",
    }
)
_SOLUTION_SET_OPERATORS = frozenset(
    {
        "Set",
        "FiniteSet",
        "SolutionSet",
        "Solutions",
        "List",
        "Tuple",
        "Union",
        "Intersection",
        "CartesianProduct",
    }
)
_DOMAIN_OPERATORS = frozenset(
    {
        "Interval",
        "Domain",
        "FunctionDomain",
        "Element",
        "NotElement",
        "Condition",
        "Conditional",
        "Piecewise",
        "Cases",
    }
)
_ROOT_RISK_OPERATORS = frozenset(
    {
        "Root",
        "Sqrt",
        "SquareRoot",
        "Surd",
        "Inverse",
        "InverseFunction",
    }
)
_INSUFFICIENT_CONDITION_OPERATORS = frozenset(
    {
        "Unknown",
        "MissingCondition",
        "Underdetermined",
    }
)
_SUPPORTED_EXPRESSION_OPERATORS = frozenset(
    {"Add", "Multiply", "Negate", "Divide", "Rational", "Power"}
)


@dataclass(frozen=True, slots=True)
class MathSemanticsFinding:
    code: str
    evidence: dict[str, object]
    remediation: str


@dataclass(frozen=True, slots=True)
class MathSemanticsEvaluation:
    question_type: str
    policy_version: str | None
    support_status: SupportStatus
    semantic_class: SemanticClass
    trigger_operator: str | None
    findings: tuple[MathSemanticsFinding, ...]

    def feature_summary(self) -> dict[str, object]:
        return {
            "availability": "available",
            "version": MATH_SEMANTICS_RULESET_VERSION,
            "question_type": self.question_type,
            "policy_version": self.policy_version,
            "support_status": self.support_status,
            "semantic_class": self.semantic_class,
            "trigger_operator": self.trigger_operator,
        }


def evaluate_math_semantics(
    *, question_type: object, policy_version: object, rule_json: object
) -> MathSemanticsEvaluation:
    """Classify only platform-owned mathematical structures.

    The result never contains the candidate prompt, raw MathJSON, expected answer,
    variable names, or solver traces.
    """

    normalized_question_type = question_type if isinstance(question_type, str) else "unknown"
    normalized_policy_version = policy_version if isinstance(policy_version, str) else None
    if normalized_question_type not in {"M1", "M2"}:
        return MathSemanticsEvaluation(
            question_type=normalized_question_type,
            policy_version=normalized_policy_version,
            support_status="not_applicable",
            semantic_class="not_applicable",
            trigger_operator=None,
            findings=(),
        )
    if not isinstance(rule_json, dict):
        return _blocked_evaluation(
            normalized_question_type,
            normalized_policy_version,
            semantic_class="unsupported_structure",
            code="math_semantics_unsupported",
            trigger_operator=None,
            remediation="Provide a supported platform-owned mathematics rule structure.",
            support_status="invalid",
        )
    if normalized_question_type == "M1":
        return _evaluate_m1(normalized_policy_version, rule_json)
    return _evaluate_m2(normalized_policy_version, rule_json)


def unavailable_math_semantics_signal(reason: str) -> dict[str, object]:
    return {
        "availability": "unavailable",
        "version": MATH_SEMANTICS_RULESET_VERSION,
        "question_type": None,
        "policy_version": None,
        "support_status": None,
        "semantic_class": None,
        "trigger_operator": None,
        "reason": reason,
    }


def _evaluate_m1(
    policy_version: str | None, rule_json: dict[str, object]
) -> MathSemanticsEvaluation:
    expected = rule_json.get("expected")
    if isinstance(expected, bool):
        return _generic_unsupported("M1", policy_version)
    if isinstance(expected, int | float) and math.isfinite(float(expected)):
        return MathSemanticsEvaluation(
            question_type="M1",
            policy_version=policy_version,
            support_status="supported",
            semantic_class="single_numeric_value",
            trigger_operator=None,
            findings=(),
        )
    if isinstance(expected, list | tuple | set):
        return _blocked_evaluation(
            "M1",
            policy_version,
            semantic_class="multiple_solution_set",
            code="m1_multiple_solution_semantics_unsupported",
            trigger_operator=_container_name(expected),
            remediation="Use M1 only for one finite numeric answer, or choose a reviewed question type.",
        )
    if isinstance(expected, dict):
        operator = expected.get("operator") or expected.get("type")
        return _blocked_evaluation(
            "M1",
            policy_version,
            semantic_class=_semantic_class_for_operator(operator),
            code=_finding_code_for_class("M1", _semantic_class_for_operator(operator)),
            trigger_operator=operator if isinstance(operator, str) else "object",
            remediation="Use M1 only for one finite numeric answer.",
        )
    return _generic_unsupported("M1", policy_version)


def _evaluate_m2(
    policy_version: str | None, rule_json: dict[str, object]
) -> MathSemanticsEvaluation:
    expected = rule_json.get("expected")
    classified = _classify_m2_value(expected, variables=_declared_variables(rule_json))
    if classified is None:
        return MathSemanticsEvaluation(
            question_type="M2",
            policy_version=policy_version,
            support_status="supported",
            semantic_class="expression_equivalence",
            trigger_operator=None,
            findings=(),
        )
    semantic_class, trigger_operator = classified
    return _blocked_evaluation(
        "M2",
        policy_version,
        semantic_class=semantic_class,
        code=_finding_code_for_class("M2", semantic_class),
        trigger_operator=trigger_operator,
        remediation=_remediation_for_class(semantic_class),
    )


def _classify_m2_value(
    value: object, *, variables: frozenset[str]
) -> tuple[SemanticClass, str | None] | None:
    if isinstance(value, bool) or value is None or isinstance(value, dict):
        return "unsupported_structure", _container_name(value)
    if isinstance(value, int | float | str):
        return None
    if not isinstance(value, list) or not value:
        return "unsupported_structure", _container_name(value)
    operator = value[0]
    if not isinstance(operator, str):
        return "unsupported_structure", "non_string_operator"
    explicit_class = _semantic_class_for_operator(operator)
    if explicit_class != "unsupported_structure":
        return explicit_class, operator
    if operator not in _SUPPORTED_EXPRESSION_OPERATORS:
        return "unsupported_structure", operator

    arguments = value[1:]
    if operator == "Divide" and len(arguments) >= 2 and _contains_declared_symbol(
        arguments[1], variables
    ):
        return "domain_restriction", operator
    if operator == "Power" and len(arguments) >= 2:
        exponent = _literal_number(arguments[1])
        if exponent is not None and exponent < 0 and _contains_declared_symbol(
            arguments[0], variables
        ):
            return "domain_restriction", operator
        if _is_fractional_exponent(arguments[1]) and _contains_declared_symbol(
            arguments[0], variables
        ):
            return "extraneous_or_missing_root_risk", operator

    for argument in arguments:
        nested = _classify_m2_value(argument, variables=variables)
        if nested is not None:
            return nested
    return None


def _semantic_class_for_operator(operator: object) -> SemanticClass:
    if not isinstance(operator, str):
        return "unsupported_structure"
    if operator in _EQUATION_OPERATORS:
        return "equation_or_inequality"
    if operator in _SOLUTION_SET_OPERATORS:
        return "multiple_solution_set"
    if operator in _DOMAIN_OPERATORS:
        return "domain_restriction"
    if operator in _ROOT_RISK_OPERATORS:
        return "extraneous_or_missing_root_risk"
    if operator in _INSUFFICIENT_CONDITION_OPERATORS:
        return "insufficient_conditions"
    return "unsupported_structure"


def _finding_code_for_class(question_type: str, semantic_class: SemanticClass) -> str:
    if question_type == "M1" and semantic_class == "multiple_solution_set":
        return "m1_multiple_solution_semantics_unsupported"
    if question_type == "M2":
        return {
            "equation_or_inequality": "m2_equation_semantics_unsupported",
            "multiple_solution_set": "m2_solution_set_semantics_unsupported",
            "domain_restriction": "m2_domain_semantics_unsupported",
            "extraneous_or_missing_root_risk": "m2_root_semantics_unsupported",
            "insufficient_conditions": "m2_insufficient_conditions_unsupported",
        }.get(semantic_class, "math_semantics_unsupported")
    return "math_semantics_unsupported"


def _remediation_for_class(semantic_class: SemanticClass) -> str:
    return {
        "equation_or_inequality": (
            "Use M2 only for expression equivalence; equations and inequalities require review."
        ),
        "multiple_solution_set": (
            "Use M2 only for one expression-equivalence target; solution sets require review."
        ),
        "domain_restriction": (
            "Remove implicit domain restrictions or use a reviewed question type."
        ),
        "extraneous_or_missing_root_risk": (
            "Use a reviewed question type for transformations that can introduce or omit roots."
        ),
        "insufficient_conditions": (
            "Add sufficient constraints and use a reviewed question type."
        ),
    }.get(semantic_class, "Use a supported M1 numeric or M2 expression-equivalence structure.")


def _blocked_evaluation(
    question_type: str,
    policy_version: str | None,
    *,
    semantic_class: SemanticClass,
    code: str,
    trigger_operator: str | None,
    remediation: str,
    support_status: SupportStatus = "blocked",
) -> MathSemanticsEvaluation:
    evidence = {
        "ruleset_version": MATH_SEMANTICS_RULESET_VERSION,
        "question_type": question_type,
        "policy_version": policy_version,
        "semantic_class": semantic_class,
        "trigger_operator": trigger_operator,
    }
    return MathSemanticsEvaluation(
        question_type=question_type,
        policy_version=policy_version,
        support_status=support_status,
        semantic_class=semantic_class,
        trigger_operator=trigger_operator,
        findings=(MathSemanticsFinding(code=code, evidence=evidence, remediation=remediation),),
    )


def _generic_unsupported(question_type: str, policy_version: str | None) -> MathSemanticsEvaluation:
    return _blocked_evaluation(
        question_type,
        policy_version,
        semantic_class="unsupported_structure",
        code="math_semantics_unsupported",
        trigger_operator=None,
        remediation="Use a supported platform-owned mathematics rule structure.",
        support_status="invalid",
    )


def _declared_variables(rule_json: dict[str, object]) -> frozenset[str]:
    variables = rule_json.get("variables")
    if not isinstance(variables, list):
        return frozenset()
    return frozenset(value for value in variables if isinstance(value, str))


def _contains_declared_symbol(value: object, variables: frozenset[str]) -> bool:
    if isinstance(value, str):
        return value in variables
    if isinstance(value, list):
        return any(_contains_declared_symbol(item, variables) for item in value[1:])
    return False


def _literal_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


def _is_fractional_exponent(value: object) -> bool:
    if not isinstance(value, list) or len(value) != 3 or value[0] != "Rational":
        return False
    numerator = _literal_number(value[1])
    denominator = _literal_number(value[2])
    return (
        numerator is not None
        and denominator is not None
        and denominator != 0
        and not float(numerator / denominator).is_integer()
    )


def _container_name(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, tuple):
        return "tuple"
    if isinstance(value, set):
        return "set"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__
