from __future__ import annotations

import re
from datetime import date


_SNAPSHOT_MODEL_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z0-9][A-Za-z0-9._-]*)-(?P<date>\d{4}-\d{2}-\d{2})"
)


def validate_immutable_openai_model_snapshot(model: str) -> str:
    """Return a model identifier only when it ends in a real ISO snapshot date."""

    match = _SNAPSHOT_MODEL_PATTERN.fullmatch(model)
    if match is None:
        raise ValueError("OpenAI model must use a dated snapshot")
    try:
        date.fromisoformat(match.group("date"))
    except ValueError as exc:
        raise ValueError("OpenAI model must use a dated snapshot") from exc
    return model
