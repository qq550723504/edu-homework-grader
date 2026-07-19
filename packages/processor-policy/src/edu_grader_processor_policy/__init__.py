from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse


class ProcessorPolicyError(ValueError):
    """Raised when a processor destination or payload crosses the privacy boundary."""


_FORBIDDEN_FIELDS = frozenset(
    {
        "tenant_id",
        "student_id",
        "school_id",
        "display_name",
        "oidc_subject",
        "email",
        "phone",
        "metadata",
        "authorization",
        "token",
    }
)


def assert_allowed_processor_url(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or host is None:
        raise ProcessorPolicyError("processor URL must be an absolute HTTP(S) URL")
    if host.casefold() not in allowed_hosts:
        raise ProcessorPolicyError(f"processor host is not allowlisted: {host}")


def assert_deidentified_payload(payload: Mapping[str, object]) -> None:
    _assert_value(payload)


def _assert_value(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProcessorPolicyError("processor payload keys must be strings")
            if key.casefold() in _FORBIDDEN_FIELDS:
                raise ProcessorPolicyError(f"forbidden processor payload field: {key}")
            _assert_value(item)
    elif isinstance(value, list):
        for item in value:
            _assert_value(item)
