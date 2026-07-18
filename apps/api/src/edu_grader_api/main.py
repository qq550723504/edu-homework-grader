from fastapi import Depends, FastAPI

from .auth import CurrentPrincipal, get_current_principal
from .routers.admin import router as admin_router
from .routers.classes import router as classes_router
from .routers.questions import router as questions_router
from .routers.questions import version_router as question_versions_router
from .settings import settings

app = FastAPI(
    title="Edu Homework Grader API",
    version="0.1.0",
    description="Core API for assignments, submissions, reviews, corrections and audit trails.",
)
app.include_router(admin_router)
app.include_router(classes_router)
app.include_router(questions_router)
app.include_router(question_versions_router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "api", "environment": settings.app_env}


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
