import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .auth import CurrentPrincipal, get_current_principal
from .db import engine
from .logging import get_secure_logger
from .routers.admin import router as admin_router
from .routers.appeals import router as appeals_router
from .routers.appeals import teacher_router as teacher_appeals_router
from .routers.classes import router as classes_router
from .routers.guardian_consents import router as guardian_consents_router
from .routers.assignments import router as assignments_router
from .routers.assignments import student_router as student_assignments_router
from .routers.questions import router as questions_router
from .routers.questions import policy_catalog_router
from .routers.questions import version_router as question_versions_router
from .routers.privacy_requests import router as privacy_requests_router
from .routers.reviews import router as reviews_router
from .routers.reviews import publication_router
from .routers.reviews import metrics_router
from .routers.teacher import router as teacher_router
from .settings import settings

app = FastAPI(
    title="Edu Homework Grader API",
    version="0.1.0",
    description="Core API for assignments, submissions, reviews, corrections and audit trails.",
)
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = get_secure_logger(__name__)
app.include_router(admin_router)
app.include_router(appeals_router)
app.include_router(teacher_appeals_router)
app.include_router(classes_router)
app.include_router(guardian_consents_router)
app.include_router(privacy_requests_router)
app.include_router(assignments_router)
app.include_router(student_assignments_router)
app.include_router(questions_router)
app.include_router(policy_catalog_router)
app.include_router(question_versions_router)
app.include_router(reviews_router)
app.include_router(publication_router)
app.include_router(metrics_router)
app.include_router(teacher_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api", "environment": settings.app_env}


@app.get("/ready", tags=["system"], response_model=None)
def ready() -> dict[str, str] | JSONResponse:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        logger.warning("readiness check failed", extra={"component": "database"})
        return JSONResponse(
            status_code=503, content={"status": "degraded", "database": "unavailable"}
        )
    return {"status": "ready", "database": "ready"}


@app.get("/v1/meta/capabilities", tags=["meta"])
def capabilities() -> dict[str, object]:
    return {
        "subjects": {
            "english": [
                "objective",
                "word_or_phrase_blank",
                "constrained_sentence",
                "short_answer_assisted",
            ],
            "mathematics": [
                "numeric",
                "expression_equivalence",
                "equation_solution",
                "multi_step",
            ],
        },
        "grading_policy": "deterministic-auto; ambiguous-review",
        "grader_base_url": settings.grader_base_url,
    }


@app.get("/v1/me", tags=["identity"])
def me(principal: CurrentPrincipal = Depends(get_current_principal)) -> dict[str, str | None]:
    return {
        "id": principal.user_id,
        "tenant_id": principal.tenant_id,
        "role": principal.role.value,
        "school_id": principal.school_id,
        "display_name": principal.display_name,
    }
