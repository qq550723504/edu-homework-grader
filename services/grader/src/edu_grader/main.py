import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .english import EnglishExactRequest, grade_exact
from .english_dependencies import (
    EnglishDependencyError,
    LanguageToolClient,
    SentenceTransformerSimilarity,
    UnavailableSimilarity,
)
from .english_orchestrator import grade_english
from .execution import load_math_execution_limits, run_math_expression
from .math_ast import (
    ExpressionGradeRequest,
    NumericGradeRequest,
    grade_expression,
    grade_numeric,
    mathjson_review_result,
)
from .mathjson import MathJsonValidationError, normalize_mathjson
from .models import GradingResult

app = FastAPI(
    title="Edu Homework Grader Service",
    version="0.1.0",
    description="Deterministic and explainable grading primitives.",
)


class NormalizeMathJsonRequest(BaseModel):
    mathjson: Any
    variables: list[str] = Field(default_factory=list, max_length=10)


class MathJsonExpressionGradeRequest(BaseModel):
    student_mathjson: Any
    expected_mathjson: Any
    variables: list[str] = Field(default_factory=list, max_length=10)
    required_form: str | None = None
    form_score: float = Field(default=0, ge=0, le=100)
    max_score: float = Field(default=1, gt=0, le=100)


class EnglishGradeRequest(BaseModel):
    question_type: str = Field(min_length=2, max_length=20)
    policy_version: str = Field(min_length=1, max_length=20)
    rule: dict[str, object]
    answer: dict[str, object]


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "grader"}


@app.post("/v1/grade/english/exact", response_model=GradingResult, tags=["english"])
def english_exact(request: EnglishExactRequest) -> GradingResult:
    return grade_exact(request)


@app.post("/v1/grade/english", response_model=GradingResult, tags=["english"])
def english_grade(request: EnglishGradeRequest) -> GradingResult:
    grammar_checker = LanguageToolClient(
        os.environ.get("LANGUAGETOOL_BASE_URL", "http://languagetool:8010/v2"),
        timeout_seconds=float(os.environ.get("LANGUAGETOOL_TIMEOUT_SECONDS", "2")),
    )
    try:
        similarity = SentenceTransformerSimilarity(
            Path(os.environ.get("ENGLISH_EMBEDDING_MODEL_DIRECTORY", "/opt/english-model")),
            model_id=os.environ.get(
                "ENGLISH_EMBEDDING_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2"
            ),
            revision=os.environ.get("ENGLISH_EMBEDDING_MODEL_REVISION", "unconfigured"),
            digest=os.environ.get("ENGLISH_EMBEDDING_MODEL_DIGEST", "unconfigured"),
        )
    except EnglishDependencyError as error:
        similarity = UnavailableSimilarity(str(error))
    return grade_english(
        request.model_dump(),
        grammar_checker=grammar_checker,
        similarity=similarity,
    )


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


@app.post("/v1/normalize/mathjson", tags=["mathematics"], response_model=None)
def normalize_mathjson_route(body: NormalizeMathJsonRequest) -> dict[str, object] | JSONResponse:
    try:
        return {"ast": normalize_mathjson(body.mathjson, body.variables)}
    except MathJsonValidationError as error:
        return JSONResponse(status_code=422, content={"code": error.code, "message": str(error)})


@app.post("/v1/grade/math/expression-v2", response_model=GradingResult, tags=["mathematics"])
def math_expression_v2(body: MathJsonExpressionGradeRequest) -> GradingResult:
    try:
        request = {
            "student_ast": normalize_mathjson(body.student_mathjson, body.variables),
            "expected_ast": normalize_mathjson(body.expected_mathjson, body.variables),
            "variables": body.variables,
            "required_form": body.required_form,
            "form_score": body.form_score,
            "max_score": body.max_score,
        }
    except MathJsonValidationError as error:
        return mathjson_review_result(error, body.max_score)
    return run_math_expression(
        request,
        load_math_execution_limits(),
    )
