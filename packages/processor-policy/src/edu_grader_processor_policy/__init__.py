from __future__ import annotations

from collections.abc import Mapping
import re
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

_EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w.+-])[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+(?![\w-])"
)
_PHONE_PATTERN = re.compile(
    r"""(?x)
    (?<!\w)
    (?:
        (?:\+?86[-.\s]?)?1[3-9]\d{9}
        | \+[1-9](?:[\s.-]?\d){7,14}
        | (?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)|\d{2,4})[\s.-]\d{2,4}[\s.-]\d{3,4}
    )
    (?!\w)
    """
)
_STUDENT_IDENTITY_PATTERN = re.compile(
    r"(?ix)(?:\b(?:student|pupil)\s*(?:name|id|number|no\.?)\b|(?:学生)?(?:姓名|名字|学号|编号))\s*[:：#]?\s*(?:[a-z0-9][a-z0-9_-]*|[\u4e00-\u9fff]{2,})"
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


def assert_deidentified_text(text: str) -> None:
    """Reject stable PII patterns before free text crosses a processor boundary."""

    if any(
        pattern.search(text) is not None
        for pattern in (_EMAIL_PATTERN, _PHONE_PATTERN, _STUDENT_IDENTITY_PATTERN)
    ):
        raise ProcessorPolicyError("free-text PII is not allowed in processor payloads")


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
