import pytest

from edu_grader.mathjson import MathJsonValidationError, normalize_mathjson


def test_normalizes_whitelisted_mathjson() -> None:
    assert normalize_mathjson(["Add", ["Multiply", 2, "x"], 6], ["x"]) == {
        "type": "add",
        "args": [
            {
                "type": "mul",
                "args": [
                    {"type": "number", "value": "2"},
                    {"type": "symbol", "name": "x"},
                ],
            },
            {"type": "number", "value": "6"},
        ],
    }


@pytest.mark.parametrize(
    ("value", "code"),
    [
        (["Assign", "x", 1], "unsupported_operator"),
        (["Divide", 1, 0], "zero_denominator"),
        (["Power", "x", 11], "exponent_out_of_range"),
        (["Add", 1, "z"], "unknown_symbol"),
    ],
)
def test_rejects_unsafe_mathjson(value: object, code: str) -> None:
    with pytest.raises(MathJsonValidationError) as error:
        normalize_mathjson(value, ["x"])

    assert error.value.code == code


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("9" * 65, "number_limit"),
        (f"0.{'1' * 33}", "number_limit"),
        ("NaN", "non_finite_number"),
        ({"num": "1"}, "unsupported_representation"),
        (["Divide", 1, "x"], "symbolic_denominator"),
    ],
)
def test_rejects_unsafe_number_and_denominator_representations(value: object, code: str) -> None:
    with pytest.raises(MathJsonValidationError) as error:
        normalize_mathjson(value, ["x"])

    assert error.value.code == code


def test_enforces_node_limit_before_building_expression() -> None:
    value: object = 1
    for _ in range(7):
        value = ["Add", value, value]

    with pytest.raises(MathJsonValidationError) as error:
        normalize_mathjson(value, [])

    assert error.value.code == "node_limit"
