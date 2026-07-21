import os
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any

from edu_grader_processor_policy import assert_allowed_processor_url, assert_deidentified_payload
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .english import EnglishExactRequest, grade_exact
from .english_dependencies import (
    EnglishDependencyError,
    LanguageToolClient,
    SentenceTransformerSimilarity,
    UnavailableSimilarity,
    _valid_similarity,
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


def _embedding_dependency_version() -> dict[str, str]:
    return {
        "id": os.environ.get(
            "ENGLISH_EMBEDDING_MODEL_ID", "sentence-transformers/all-MiniLM-L6-v2"
        ),
        "revision": os.environ.get("ENGLISH_EMBEDDING_MODEL_REVISION", "unconfigured"),
        "digest": os.environ.get("ENGLISH_EMBEDDING_MODEL_DIGEST", "unconfigured"),
    }


def _runtime_dependency_versions() -> dict[str, str]:
    try:
        sentence_transformers_version = version("sentence-transformers")
    except PackageNotFoundError:
        sentence_transformers_version = "unavailable"
    return {"sentence-transformers": sentence_transformers_version}


def _load_semantic_similarity(
    embedding_version: dict[str, str],
) -> SentenceTransformerSimilarity | UnavailableSimilarity:
    try:
        return SentenceTransformerSimilarity(
            Path(os.environ.get("ENGLISH_EMBEDDING_MODEL_DIRECTORY", "/opt/english-model")),
            model_id=embedding_version["id"],
            revision=embedding_version["revision"],
            digest=embedding_version["digest"],
        )
    except EnglishDependencyError as error:
        return UnavailableSimilarity(str(error))


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.embedding_dependency_version = _embedding_dependency_version()
    application.state.runtime_dependency_versions = _runtime_dependency_versions()
    application.state.semantic_similarity = _load_semantic_similarity(
        application.state.embedding_dependency_version
    )
    yield


app = FastAPI(
    title="Edu Homework Grader Service",
    version="0.1.0",
    description="Deterministic and explainable grading primitives.",
    lifespan=lifespan,
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


class SemanticSimilarityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=10_000)]
    comparisons: list[Annotated[str, Field(min_length=1, max_length=10_000)]] = Field(
        min_length=1, max_length=128
    )


class SemanticSimilarityResponse(BaseModel):
    scores: list[float]
    embedding: dict[str, str]


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "grader"}


@app.get("/ready", tags=["system"], response_model=None)
def ready() -> dict[str, str] | JSONResponse:
    similarity = app.state.semantic_similarity
    if isinstance(similarity, UnavailableSimilarity):
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "english_embedding_model": "unavailable"},
        )
    return {"status": "ready", "english_embedding_model": "ready"}


@app.post("/v1/grade/english/exact", response_model=GradingResult, tags=["english"])
def english_exact(request: EnglishExactRequest) -> GradingResult:
    return grade_exact(request)


@app.post("/v1/grade/english", response_model=GradingResult, tags=["english"])
def english_grade(request: EnglishGradeRequest) -> GradingResult:
    payload = request.model_dump()
    assert_deidentified_payload(payload)
    languagetool_base_url = os.environ.get("LANGUAGETOOL_BASE_URL", "http://languagetool:8010/v2")
    assert_allowed_processor_url(languagetool_base_url, _processor_allowed_hosts())
    grammar_checker = LanguageToolClient(
        languagetool_base_url,
        timeout_seconds=float(os.environ.get("LANGUAGETOOL_TIMEOUT_SECONDS", "2")),
    )
    result = grade_english(
        payload,
        grammar_checker=grammar_checker,
        similarity=app.state.semantic_similarity,
    )
    return result.model_copy(
        update={
            "dependency_versions": {
                "embedding": app.state.embedding_dependency_version,
                "runtime": app.state.runtime_dependency_versions,
            }
        }
    )


@app.post(
    "/v1/semantic-similarity",
    response_model=SemanticSimilarityResponse,
    tags=["internal"],
)
def semantic_similarity(request: SemanticSimilarityRequest) -> SemanticSimilarityResponse:
    payload = request.model_dump()
    assert_deidentified_payload(payload)
    try:
        scores = app.state.semantic_similarity.score_many(request.query, request.comparisons)
        if len(scores) != len(request.comparisons):
            raise EnglishDependencyError("English embedding model returned an incomplete batch.")
        validated_scores = [_valid_similarity(score) for score in scores]
    except Exception as error:
        raise HTTPException(status_code=503, detail="semantic similarity is unavailable") from error
    return SemanticSimilarityResponse(
        scores=validated_scores,
        embedding=app.state.embedding_dependency_version,
    )


def _processor_allowed_hosts() -> frozenset[str]:
    return frozenset(
        item.strip().casefold()
        for item in os.environ.get(
            "PROCESSOR_ALLOWED_HOSTS", "grader,languagetool,localhost"
        ).split(",")
        if item.strip()
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
