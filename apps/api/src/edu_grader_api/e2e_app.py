from __future__ import annotations

from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
import os
from pathlib import Path
import tempfile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from . import models as _models  # noqa: F401
from .auth import get_token_verifier
from .db import Base, get_session
from .e2e_support import (
    DeterministicM2Client,
    StaticE2EVerifier,
    seed_demo_assignment,
)
from .main import app as production_app
from .routers import questions as questions_router
from .services import assignments as assignments_service
from .services import reviews as reviews_service


def _database_url() -> str:
    raw_url = os.environ.get("E2E_DATABASE_URL")
    if not raw_url:
        raise RuntimeError("E2E_DATABASE_URL is required")

    url = make_url(raw_url)
    if url.get_backend_name() != "sqlite" or not url.database:
        raise RuntimeError("E2E_DATABASE_URL must use a file-backed SQLite database")

    database_path = Path(url.database).resolve()
    temporary_directory = Path(tempfile.gettempdir()).resolve()
    if database_path == temporary_directory or not database_path.is_relative_to(
        temporary_directory
    ):
        raise RuntimeError("E2E_DATABASE_URL must be beneath the process temporary directory")
    return raw_url


E2E_ENGINE = create_engine(
    _database_url(),
    connect_args={"check_same_thread": False},
)
E2ESessionLocal = sessionmaker(
    bind=E2E_ENGINE,
    autoflush=False,
    expire_on_commit=False,
)


def e2e_session() -> Generator[Session, None, None]:
    with E2ESessionLocal() as session:
        yield session


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    original_question_client = questions_router.HttpGraderClient
    original_assignment_client = assignments_service.HttpGraderClient
    original_review_client = reviews_service.HttpGraderClient
    questions_router.HttpGraderClient = DeterministicM2Client
    assignments_service.HttpGraderClient = DeterministicM2Client
    reviews_service.HttpGraderClient = DeterministicM2Client
    try:
        Base.metadata.create_all(E2E_ENGINE)
        with E2ESessionLocal() as session:
            seed_demo_assignment(session)
        yield
    finally:
        questions_router.HttpGraderClient = original_question_client
        assignments_service.HttpGraderClient = original_assignment_client
        reviews_service.HttpGraderClient = original_review_client
        E2E_ENGINE.dispose()


app = FastAPI(title="Edu Homework Grader E2E API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:13000"],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
)
app.include_router(production_app.router)

app.dependency_overrides[get_token_verifier] = lambda: StaticE2EVerifier()
app.dependency_overrides[get_session] = e2e_session
