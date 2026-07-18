import edu_grader.execution as execution
import edu_grader.main as grader_main
from edu_grader.execution import (
    MathExecutionLimits,
    load_math_execution_limits,
    run_math_expression,
)
from edu_grader.main import app
from fastapi.testclient import TestClient
from edu_grader.models import GradingResult


def _limits() -> MathExecutionLimits:
    return MathExecutionLimits(cpu_seconds=1, memory_bytes=134_217_728, timeout_seconds=5)


def _request() -> dict[str, object]:
    return {
        "student_ast": {
            "type": "add",
            "args": [{"type": "symbol", "name": "x"}, {"type": "number", "value": "1"}],
        },
        "expected_ast": {
            "type": "add",
            "args": [{"type": "number", "value": "1"}, {"type": "symbol", "name": "x"}],
        },
        "variables": ["x"],
        "required_form": None,
        "form_score": 0,
        "max_score": 1,
    }


def test_math_worker_returns_deterministic_result() -> None:
    result = run_math_expression(_request(), _limits())

    assert result.decision == "auto_accepted"
    assert result.score == 1


def test_execution_limits_have_safe_defaults_and_allow_environment_overrides() -> None:
    assert load_math_execution_limits({}) == MathExecutionLimits(
        cpu_seconds=1, memory_bytes=134_217_728, timeout_seconds=1.0
    )
    assert load_math_execution_limits(
        {
            "GRADER_MATH_CPU_SECONDS": "2",
            "GRADER_MATH_MEMORY_BYTES": "268435456",
            "GRADER_MATH_TIMEOUT_SECONDS": "3.5",
        }
    ) == MathExecutionLimits(cpu_seconds=2, memory_bytes=268_435_456, timeout_seconds=3.5)


def test_timeout_becomes_review_result(monkeypatch) -> None:
    monkeypatch.setattr(execution, "_join_worker", lambda *_: False)

    result = run_math_expression(_request(), _limits())

    assert result.decision == "needs_review"
    assert result.requires_review is True
    assert result.criteria[0].code == "execution_timeout"


def test_normalizer_endpoint_returns_ast_and_typed_error() -> None:
    with TestClient(app) as client:
        normalized = client.post(
            "/v1/normalize/mathjson", json={"mathjson": ["Add", "x", 1], "variables": ["x"]}
        )
        invalid = client.post(
            "/v1/normalize/mathjson", json={"mathjson": ["Assign", "x", 1], "variables": ["x"]}
        )

    assert normalized.status_code == 200
    assert normalized.json()["ast"]["type"] == "add"
    assert invalid.status_code == 422
    assert invalid.json()["code"] == "unsupported_operator"


def test_v2_endpoint_normalizes_before_starting_worker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(request: dict[str, object], _: MathExecutionLimits) -> GradingResult:
        captured.update(request)
        return GradingResult(
            decision="auto_accepted",
            score=1,
            max_score=1,
            confidence=1,
            criteria=[],
            feedback=[],
        )

    monkeypatch.setattr(grader_main, "run_math_expression", fake_run)
    with TestClient(app) as client:
        response = client.post(
            "/v1/grade/math/expression-v2",
            json={
                "student_mathjson": ["Add", "x", 1],
                "expected_mathjson": ["Add", 1, "x"],
                "variables": ["x"],
                "max_score": 1,
            },
        )

    assert response.status_code == 200
    assert captured["student_ast"] == {
        "type": "add",
        "args": [{"type": "symbol", "name": "x"}, {"type": "number", "value": "1"}],
    }
    assert "student_mathjson" not in captured


def test_v2_endpoint_maps_worker_timeout_to_review(monkeypatch) -> None:
    monkeypatch.setattr(execution, "_join_worker", lambda *_: False)
    with TestClient(app) as client:
        response = client.post(
            "/v1/grade/math/expression-v2",
            json={
                "student_mathjson": ["Add", "x", 1],
                "expected_mathjson": ["Add", 1, "x"],
                "variables": ["x"],
                "max_score": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["decision"] == "needs_review"
    assert response.json()["criteria"][0]["code"] == "execution_timeout"
