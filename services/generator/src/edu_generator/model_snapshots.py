from __future__ import annotations

import re
from datetime import date


_SNAPSHOT_MODEL_ID_PATTERN = re.compile(
    r"(?P<prefix>[A-Za-z0-9][A-Za-z0-9._-]*)-"
    r"(?P<snapshot>\d{4}-\d{2}-\d{2}|\d{4})"
)
_FINE_TUNED_MODEL_ID_PATTERN = re.compile(
    r"ft:"
    r"[A-Za-z0-9][A-Za-z0-9._-]*:"
    r"[A-Za-z0-9][A-Za-z0-9_-]*:"
    r"[A-Za-z0-9][A-Za-z0-9_-]*:"
    r"[A-Za-z0-9][A-Za-z0-9_-]*"
)
_VERSIONED_GPT_5_6_MODEL_IDS = frozenset(
    {"gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"}
)
_INVALID_MODEL_ID_MESSAGE = "OpenAI model must use an immutable model ID"


def validate_immutable_openai_model_id(model: str) -> str:
    """Return only a recognized immutable OpenAI model identifier."""

    if model in _VERSIONED_GPT_5_6_MODEL_IDS:
        return model

    if _FINE_TUNED_MODEL_ID_PATTERN.fullmatch(model) is not None:
        return model

    match = _SNAPSHOT_MODEL_ID_PATTERN.fullmatch(model)
    if match is None:
        raise ValueError(_INVALID_MODEL_ID_MESSAGE)

    snapshot = match.group("snapshot")
    try:
        if len(snapshot) == 4:
            date(2000, int(snapshot[:2]), int(snapshot[2:]))
        else:
            date.fromisoformat(snapshot)
    except ValueError as exc:
        raise ValueError(_INVALID_MODEL_ID_MESSAGE) from exc
    return model
