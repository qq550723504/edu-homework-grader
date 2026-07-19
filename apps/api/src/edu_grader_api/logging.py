from __future__ import annotations

import json
import logging
from collections.abc import Mapping


_SENSITIVE_FIELDS = frozenset(
    {
        "answer",
        "answer_json",
        "authorization",
        "token",
        "password",
        "oidc_subject",
        "school_id",
        "display_name",
        "email",
        "database_url",
        "connection_string",
    }
)


def sanitize_log_fields(fields: Mapping[str, object]) -> dict[str, object]:
    return {key: _sanitize_value(key, value) for key, value in fields.items()}


def get_secure_logger(name: str) -> logging.LoggerAdapter[logging.Logger]:
    return _SecureLoggerAdapter(logging.getLogger(name), {})


class _SecureLoggerAdapter(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: object, kwargs: dict[str, object]) -> tuple[object, dict[str, object]]:
        extra = kwargs.pop("extra", {})
        fields = extra.get("fields", {}) if isinstance(extra, Mapping) else {}
        safe_fields = sanitize_log_fields(fields) if isinstance(fields, Mapping) else {}
        return f"{msg} {json.dumps(safe_fields, ensure_ascii=False, sort_keys=True)}", kwargs


def _sanitize_value(key: str, value: object) -> object:
    if key.casefold() in _SENSITIVE_FIELDS:
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {child_key: _sanitize_value(child_key, child) for child_key, child in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(key, child) for child in value]
    if isinstance(value, str):
        return value
    return value
