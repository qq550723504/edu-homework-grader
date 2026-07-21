"""Versioned prompt fingerprints used by question duplicate checks."""

from dataclasses import dataclass
from hashlib import sha256
import re
import unicodedata


FINGERPRINT_VERSION = "question-fingerprint-v1"
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PromptFingerprints:
    version: str
    exact_hash: str
    normalized_hash: str


def normalize_prompt(prompt: str) -> str:
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", prompt).strip()).casefold()


def fingerprint_prompt(prompt: str) -> PromptFingerprints:
    return PromptFingerprints(
        version=FINGERPRINT_VERSION,
        exact_hash=sha256(prompt.encode("utf-8")).hexdigest(),
        normalized_hash=sha256(normalize_prompt(prompt).encode("utf-8")).hexdigest(),
    )
