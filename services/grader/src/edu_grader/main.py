from fastapi import FastAPI, HTTPException

from .english import EnglishExactRequest, grade_exact
from .math_ast import (
    ExpressionGradeRequest,
    NumericGradeRequest,
    grade_expression,
    grade_numeric,
)
from .models import GradingResult

app = FastAPI(
    title="Edu Homework Grader Service",
    version="0.1.0",
    description="Deterministic and explainable grading primitives.",
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "grader"}


@app.post("/v1/grade/english/exact", response_model=GradingResult, tags=["english"])
def english_exact(request: EnglishExactRequest) -> GradingResult:
    return grade_exact(request)


@app.post("/v1/grade/math/numeric", response_model=GradingResult, tags=["mathematics"])
def math_numeric(request: NumericGradeRequest) -> GradingResult:
    try:
        return grade_numeric(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/v1/grade/math/expression", response_model=GradingResult, tags=["mathematics"])
def math_expression(request: ExpressionGradeRequest) -> GradingResult:
    try:
        return grade_expression(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
