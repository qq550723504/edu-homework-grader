from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx


class EnglishDependencyError(RuntimeError):
    """Raised when an optional English scoring dependency cannot provide a safe signal."""


@dataclass(frozen=True)
class GrammarMatch:
    offset: int
    length: int
    rule_id: str
    category: str
    issue_type: str
    message: str
    replacements: list[str]


class GrammarChecker(Protocol):
    def check(self, text: str) -> list[GrammarMatch]: ...


class SemanticSimilarity(Protocol):
    def score(self, left: str, right: str) -> float: ...


class _HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


HttpPost = Callable[..., _HttpResponse]


class LanguageToolClient:
    def __init__(
        self, base_url: str, *, timeout_seconds: float, post: HttpPost = httpx.post
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._post = post

    def check(self, text: str) -> list[GrammarMatch]:
        try:
            response = self._post(
                f"{self._base_url}/check",
                data={"text": text, "language": "en-US"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, OSError, ValueError) as error:
            raise EnglishDependencyError("LanguageTool is unavailable.") from error
        if not isinstance(payload, dict):
            raise EnglishDependencyError("LanguageTool returned an invalid response.")
        matches = payload.get("matches")
        if not isinstance(matches, list):
            raise EnglishDependencyError("LanguageTool response has no matches list.")
        return [_grammar_match(item) for item in matches]


class StaticSimilarity:
    """Test-only similarity implementation that enforces the production score contract."""

    def __init__(self, value: float) -> None:
        self._value = value

    def score(self, left: str, right: str) -> float:
        return _valid_similarity(self._value)


class SentenceTransformerSimilarity:
    def __init__(
        self,
        model_directory: Path,
        *,
        model_id: str,
        revision: str,
        digest: str,
    ) -> None:
        metadata = _load_model_metadata(model_directory)
        if metadata != {"model_id": model_id, "revision": revision, "digest": digest}:
            raise EnglishDependencyError(
                "English embedding model metadata does not match configuration."
            )
        try:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(str(model_directory), local_files_only=True)
        except (ImportError, OSError, ValueError) as error:
            raise EnglishDependencyError("English embedding model is unavailable.") from error

    def score(self, left: str, right: str) -> float:
        try:
            vectors = self._model.encode([left, right], normalize_embeddings=True)
            score = sum(float(a) * float(b) for a, b in zip(vectors[0], vectors[1], strict=True))
        except (OSError, TypeError, ValueError) as error:
            raise EnglishDependencyError(
                "English embedding model could not score the answer."
            ) from error
        return _valid_similarity(score)


def _grammar_match(value: object) -> GrammarMatch:
    if not isinstance(value, dict):
        raise EnglishDependencyError("LanguageTool returned an invalid match.")
    offset = value.get("offset")
    length = value.get("length")
    message = value.get("message")
    rule = value.get("rule")
    replacements = value.get("replacements", [])
    if (
        isinstance(offset, bool)
        or not isinstance(offset, int)
        or offset < 0
        or isinstance(length, bool)
        or not isinstance(length, int)
        or length <= 0
        or not isinstance(message, str)
        or not isinstance(rule, dict)
        or not isinstance(replacements, list)
    ):
        raise EnglishDependencyError("LanguageTool returned an invalid match.")
    rule_id = rule.get("id")
    issue_type = rule.get("issueType")
    category_value = rule.get("category")
    if (
        not isinstance(rule_id, str)
        or not isinstance(issue_type, str)
        or not isinstance(category_value, dict)
    ):
        raise EnglishDependencyError("LanguageTool returned invalid rule metadata.")
    category = category_value.get("id")
    if not isinstance(category, str):
        raise EnglishDependencyError("LanguageTool returned invalid rule metadata.")
    values: list[str] = []
    for replacement in replacements:
        if not isinstance(replacement, dict) or not isinstance(replacement.get("value"), str):
            raise EnglishDependencyError("LanguageTool returned an invalid replacement.")
        values.append(replacement["value"])
    return GrammarMatch(
        offset=offset,
        length=length,
        rule_id=rule_id,
        category=category,
        issue_type=issue_type,
        message=message,
        replacements=values,
    )


def _load_model_metadata(directory: Path) -> dict[str, str]:
    try:
        value = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise EnglishDependencyError("English embedding model metadata is unavailable.") from error
    if not isinstance(value, dict) or set(value) != {"model_id", "revision", "digest"}:
        raise EnglishDependencyError("English embedding model metadata is invalid.")
    if not all(isinstance(item, str) and item for item in value.values()):
        raise EnglishDependencyError("English embedding model metadata is invalid.")
    return value


def _valid_similarity(value: float) -> float:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise EnglishDependencyError("invalid similarity score")
    return value
