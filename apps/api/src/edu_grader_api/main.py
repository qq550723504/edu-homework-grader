from fastapi import FastAPI

from .settings import settings

app = FastAPI(
    title="Edu Homework Grader API",
    version="0.1.0",
    description="Core API for assignments, submissions, reviews, corrections and audit trails.",
)


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
